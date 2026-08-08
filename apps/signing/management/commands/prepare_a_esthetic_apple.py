import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp, Release


EDITABLE_STATES = {
    'PREPARE_FOR_SUBMISSION',
    'DEVELOPER_REJECTED',
    'REJECTED',
    'METADATA_REJECTED',
}


class Command(BaseCommand):
    help = 'Prepare A+ Esthetic App Store metadata and attach a processed build, without submitting for review.'

    def add_arguments(self, parser):
        parser.add_argument('--app-version', default='1.0.0')
        parser.add_argument('--build-number', type=int, default=None)

    def handle(self, *args, **options):
        app = MobileApp.objects.select_related('apple_account').get(slug='a-esthetic')
        version_name = options['app_version']
        build_number = options['build_number']

        releases = Release.objects.filter(app=app, version_name=version_name)
        if build_number is not None:
            releases = releases.filter(build_number=build_number)
        release = releases.order_by('-build_number').first()
        if not release:
            requested = f' build {build_number}' if build_number is not None else ''
            raise CommandError(f'Release {version_name}{requested} does not exist.')

        build = (
            release.builds
            .filter(platform='ios', status='succeeded')
            .exclude(external_build_id='')
            .order_by('-finished_at', '-created_at')
            .first()
        )
        if not build or not build.external_build_id:
            raise CommandError(
                f'Processed iOS build is not available for {version_name} ({release.build_number}).'
            )
        if not app.apple_account_id or not app.apple_account.configured:
            raise CommandError('Apple account is not configured.')

        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        versions = client.request(
            'GET',
            f"/apps/{record['id']}/appStoreVersions?filter[platform]=IOS&limit=50",
        ).get('data', [])

        version = next(
            (v for v in versions if v.get('attributes', {}).get('versionString') == release.version_name),
            None,
        )
        if not version:
            editable = [
                v for v in versions
                if v.get('attributes', {}).get('appStoreState') in EDITABLE_STATES
            ]
            if len(editable) != 1:
                raise CommandError(
                    'Could not safely identify exactly one editable iOS App Store version. '
                    f'Found {len(editable)} editable versions.'
                )
            version = editable[0]
            current = version.get('attributes', {}).get('versionString')
            body = {
                'data': {
                    'type': 'appStoreVersions',
                    'id': version['id'],
                    'attributes': {'versionString': release.version_name},
                }
            }
            version = client.request(
                'PATCH',
                f"/appStoreVersions/{version['id']}",
                data=json.dumps(body),
            )['data']
            self.stdout.write(f'version_aligned={current}->{release.version_name}')
        else:
            self.stdout.write('version_aligned=already')

        # First-version localization: intentionally omit whatsNew, which is only
        # applicable to updates. Populate only the fields shown on the product page.
        for loc in app.localizations.all():
            existing = client.request(
                'GET',
                f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations?filter[locale]={loc.locale}&limit=1",
            ).get('data', [])
            attrs = {
                'description': loc.full_description,
                'keywords': loc.keywords,
                'marketingUrl': app.marketing_url,
                'promotionalText': loc.promotional_text,
                'supportUrl': app.support_url,
            }
            attrs = {k: v for k, v in attrs.items() if v}
            if existing:
                item_id = existing[0]['id']
                body = {'data': {'type': 'appStoreVersionLocalizations', 'id': item_id, 'attributes': attrs}}
                client.request('PATCH', f'/appStoreVersionLocalizations/{item_id}', data=json.dumps(body))
            else:
                body = {
                    'data': {
                        'type': 'appStoreVersionLocalizations',
                        'attributes': {'locale': loc.locale, **attrs},
                        'relationships': {
                            'appStoreVersion': {
                                'data': {'type': 'appStoreVersions', 'id': version['id']}
                            }
                        },
                    }
                }
                client.request('POST', '/appStoreVersionLocalizations', data=json.dumps(body))

        version_attrs = {
            'copyright': '2026 A+ Esthetic GmbH',
            'releaseType': 'AFTER_APPROVAL',
        }
        client.request(
            'PATCH',
            f"/appStoreVersions/{version['id']}",
            data=json.dumps({
                'data': {
                    'type': 'appStoreVersions',
                    'id': version['id'],
                    'attributes': version_attrs,
                }
            }),
        )
        client.attach_build(version['id'], build.external_build_id)
        client.set_review_details(version['id'], app)

        self.stdout.write(self.style.SUCCESS('apple_version_prepared=yes'))
        self.stdout.write(f"app_id={record['id']}")
        self.stdout.write(f"version_id={version['id']}")
        self.stdout.write(f"build_id={build.external_build_id}")
        self.stdout.write(f"version_string={release.version_name}")
        self.stdout.write(f"build_number={release.build_number}")
