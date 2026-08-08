from django.db import migrations


def create_initial_release(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')

    app = MobileApp.objects.filter(slug='a-esthetic').first()
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
            'release_notes': 'Erste Version des A+ Esthetic Kundenclubs.',
        },
    )
    Build.objects.get_or_create(release=release, platform='android')
    Build.objects.get_or_create(release=release, platform='ios')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0002_bootstrap_a_esthetic'),
    ]

    operations = [
        migrations.RunPython(create_initial_release, noop_reverse),
    ]
