from django.db import migrations


def retry_aplus_solution_android(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-plus-solution').first()
    if not app:
        return

    release = Release.objects.filter(app=app, version_name='1.0.0', build_number=1).first()
    if not release:
        return

    build, _ = Build.objects.get_or_create(release=release, platform='android')

    if Job.objects.filter(
        app=app,
        release=release,
        build=build,
        type='build_android',
        status__in=['queued', 'running', 'succeeded'],
    ).exists():
        return

    build.status = 'queued'
    build.logs = ''
    build.save(update_fields=['status', 'logs', 'updated_at'])
    release.status = 'building'
    release.save(update_fields=['status', 'updated_at'])

    Job.objects.create(
        type='build_android',
        app=app,
        release=release,
        build=build,
        payload={'retry_reason': 'fix-gradle-signing-config-placement'},
        available_to_agents=True,
        required_platform='linux',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0012_queue_aplus_solution_android_bootstrap'),
    ]

    operations = [
        migrations.RunPython(retry_aplus_solution_android, noop_reverse),
    ]
