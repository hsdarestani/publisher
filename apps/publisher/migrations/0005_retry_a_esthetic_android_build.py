from django.db import migrations


def retry_android_build(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-esthetic').first()
    if not app:
        return
    release = Release.objects.filter(app=app, version_name='1.0.0', build_number=1).first()
    if not release:
        return
    build, _ = Build.objects.get_or_create(release=release, platform='android')

    # Only retry when no live/successful build job remains. The previous failure
    # was caused by the cloud runner using Java 17 while Capacitor 8 requires 21.
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
        payload={'retry_reason': 'cloud-linux-java21'},
        available_to_agents=True,
        required_platform='linux',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0004_queue_a_esthetic_android_build'),
    ]

    operations = [
        migrations.RunPython(retry_android_build, noop_reverse),
    ]
