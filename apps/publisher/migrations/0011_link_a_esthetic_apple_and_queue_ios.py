from django.db import migrations


APPLE_KEY_ID = 'WPGF7226P8'


def link_and_queue_ios(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    StoreAccount = apps.get_model('publisher', 'StoreAccount')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-esthetic').first()
    if not app:
        return

    apple = StoreAccount.objects.filter(
        provider='apple',
        enabled=True,
        apple_key_id=APPLE_KEY_ID,
    ).exclude(credential_blob='').exclude(apple_issuer_id='').first()
    if not apple:
        return

    if app.apple_account_id != apple.pk:
        app.apple_account_id = apple.pk
        app.save(update_fields=['apple_account', 'updated_at'])

    release = Release.objects.filter(
        app=app,
        version_name='1.0.0',
        build_number=1,
    ).first()
    if not release:
        return

    build, _ = Build.objects.get_or_create(release=release, platform='ios')

    if build.status == 'succeeded':
        return

    live_job = Job.objects.filter(
        app=app,
        release=release,
        build=build,
        type='build_ios',
        status__in=['queued', 'running', 'succeeded'],
    ).exists()
    if live_job:
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
        payload={'source': 'apple-account-connected'},
        available_to_agents=True,
        required_platform='macos',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0010_set_a_esthetic_review_login'),
    ]

    operations = [
        migrations.RunPython(link_and_queue_ios, noop_reverse),
    ]
