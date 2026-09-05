from django.db import migrations


SOURCE_COMMIT = '9a4b6c048e318e2babf607371682db20be8c7179'
RELEASE_NOTES = (
    'Kundenfarben korrigiert: Martha/Marthas Finest bernsteingelb; '
    'Messe Frankfurt, OMMIA/OMNIA und Hofgut weiß.'
)


def queue_customer_color_release(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    AppLocalization = apps.get_model('publisher', 'AppLocalization')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-plus-solution').first()
    if not app:
        return

    # The release is useful only on an installation that already owns both store
    # connections. CI/test databases may not have them; in that case migration is
    # deliberately a no-op instead of creating impossible store work.
    if not app.google_account_id or not app.apple_account_id or not app.repository_url:
        return

    cfg = dict(app.build_config or {})
    cfg['android_command'] = 'bash frontend/scripts/build-publisher-android.sh'
    cfg['android_artifact'] = 'frontend/android/app/build/outputs/bundle/release/*.aab'
    cfg['ios_command'] = 'bash frontend/scripts/build-publisher-ios-opaque.sh'
    cfg['ios_artifact'] = 'frontend/ios/build/export/*.ipa'
    env = dict(cfg.get('env') or {})
    env['VITE_API_URL'] = 'https://app.aplus-solution.de/api'
    cfg['env'] = env
    app.build_config = cfg
    app.requires_login = True
    app.review_notes = (
        'A+ Solution is the internal workforce application used by A+ Solution GmbH. '
        'This update corrects fixed customer colors in the schedule: all Martha/Marthas Finest '
        'locations use amber yellow, while Messe Frankfurt, OMMIA/OMNIA and Hofgut use white. '
        'The supplied App Review account remains the dedicated active employee test account. '
        'There are no in-app purchases.'
    )
    app.save(update_fields=['build_config', 'requires_login', 'review_notes', 'updated_at'])

    localization = AppLocalization.objects.filter(app=app, locale='de-DE').first()
    if localization:
        localization.release_notes = (
            'Kundenfarben im Dienstplan korrigiert: Martha/Marthas Finest einheitlich '
            'bernsteingelb; Messe Frankfurt, OMMIA/OMNIA und Hofgut weiß.'
        )
        localization.save(update_fields=['release_notes', 'updated_at'])

    latest = Release.objects.filter(app=app).order_by('-build_number', '-created_at').first()
    version_name = latest.version_name if latest and latest.version_name else '1.0.9'
    db_max = max(Release.objects.filter(app=app).values_list('build_number', flat=True), default=0)
    build_number = max(int(db_max) + 1, 20)

    release, _ = Release.objects.get_or_create(
        app=app,
        version_name=version_name,
        build_number=build_number,
    )
    release.status = 'building'
    release.source_branch = 'main'
    release.source_commit = SOURCE_COMMIT
    release.android_track = 'production'
    release.android_rollout = 1
    release.ios_release_type = 'automatic'
    release.auto_submit = True
    release.release_notes = RELEASE_NOTES
    release.save(update_fields=[
        'status', 'source_branch', 'source_commit', 'android_track',
        'android_rollout', 'ios_release_type', 'auto_submit', 'release_notes',
        'updated_at',
    ])

    for platform, job_type, runner in (
        ('android', 'build_android', 'linux'),
        ('ios', 'build_ios', 'macos'),
    ):
        build, _ = Build.objects.get_or_create(release=release, platform=platform)
        if build.status == 'succeeded' and build.artifact:
            continue
        if Job.objects.filter(
            release=release,
            build=build,
            type=job_type,
            status__in=['queued', 'running', 'succeeded'],
        ).exists():
            continue

        build.status = 'queued'
        build.logs = ''
        build.external_build_id = ''
        build.metadata = {}
        build.save(update_fields=[
            'status', 'logs', 'external_build_id', 'metadata', 'updated_at'
        ])

        Job.objects.create(
            type=job_type,
            app=app,
            release=release,
            build=build,
            payload={
                'source': 'customer-color-release-20260905',
                'source_commit': SOURCE_COMMIT,
            },
            available_to_agents=True,
            required_platform=runner,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0016_link_aplus_solution_apple_and_queue_ios'),
    ]

    operations = [
        migrations.RunPython(queue_customer_color_release, noop_reverse),
    ]
