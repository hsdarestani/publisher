from django.db import migrations


def queue_ios_if_ready(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-esthetic').first()
    if not app or not app.apple_account_id:
        return

    release = Release.objects.filter(app=app, version_name='1.0.0', build_number=1).first()
    if not release:
        return

    build, _ = Build.objects.get_or_create(release=release, platform='ios')
    if build.status == 'succeeded':
        return

    if Job.objects.filter(
        app=app,
        release=release,
        build=build,
        type='build_ios',
        status__in=['queued', 'running', 'succeeded'],
    ).exists():
        return

    build.status = 'queued'
    build.logs = ''
    build.save(update_fields=['status', 'logs', 'updated_at'])
    release.status = 'building'
    release.save(update_fields=['status', 'updated_at'])
    Job.objects.create(
        type='build_ios',
        app=app,
        release=release,
        build=build,
        payload={'source': 'a-esthetic-bootstrap'},
        available_to_agents=True,
        required_platform='macos',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0007_link_a_esthetic_store_accounts'),
    ]

    operations = [
        migrations.RunPython(queue_ios_if_ready, noop_reverse),
    ]
