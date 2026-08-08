from django.db import migrations


def queue_aplus_solution_android_bootstrap(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-plus-solution').first()
    if not app:
        return

    release, _ = Release.objects.get_or_create(
        app=app,
        version_name='1.0.0',
        build_number=1,
        defaults={
            'status': 'draft',
            'source_branch': 'main',
            'android_track': 'internal',
            'android_rollout': 1,
            'ios_release_type': 'manual',
            'auto_submit': False,
            'release_notes': 'Erste mobile Version der A+ Solution Workforce-App.',
        },
    )

    build, _ = Build.objects.get_or_create(release=release, platform='android')

    already = Job.objects.filter(
        app=app,
        release=release,
        build=build,
        type='build_android',
        status__in=['queued', 'running', 'succeeded'],
    ).exists()
    if already:
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
        payload={},
        available_to_agents=True,
        required_platform='linux',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0011_bootstrap_aplus_solution'),
    ]

    operations = [
        migrations.RunPython(queue_aplus_solution_android_bootstrap, noop_reverse),
    ]
