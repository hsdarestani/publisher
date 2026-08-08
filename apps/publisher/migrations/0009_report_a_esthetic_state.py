from django.db import migrations


def report_state(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    AppAsset = apps.get_model('publisher', 'AppAsset')
    Build = apps.get_model('publisher', 'Build')

    app = MobileApp.objects.filter(slug='a-esthetic').first()
    if not app:
        print('A_ESTHETIC_STATE app_exists=no')
        return

    release = app.releases.filter(version_name='1.0.0', build_number=1).first()
    android_build = None
    ios_build = None
    if release:
        android_build = Build.objects.filter(release=release, platform='android').first()
        ios_build = Build.objects.filter(release=release, platform='ios').first()

    icon_ready = AppAsset.objects.filter(
        app=app,
        kind='icon',
        platform__in=['shared', 'android', 'ios'],
    ).exists()

    print(
        'A_ESTHETIC_STATE '
        f'app_exists=yes '
        f'google_linked={"yes" if app.google_account_id else "no"} '
        f'apple_linked={"yes" if app.apple_account_id else "no"} '
        f'reviewer_username={"yes" if bool(app.review_username) else "no"} '
        f'reviewer_password_blob={"yes" if bool(app.review_password_blob) else "no"} '
        f'icon_ready={"yes" if icon_ready else "no"} '
        f'android_build={getattr(android_build, "status", "missing")} '
        f'ios_build={getattr(ios_build, "status", "missing")}'
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0008_queue_a_esthetic_ios_if_ready'),
    ]

    operations = [
        migrations.RunPython(report_state, noop_reverse),
    ]
