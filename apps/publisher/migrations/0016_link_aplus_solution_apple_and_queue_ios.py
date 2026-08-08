from django.db import migrations


def link_and_queue_aplus_solution_ios(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    StoreAccount = apps.get_model('publisher', 'StoreAccount')
    Release = apps.get_model('publisher', 'Release')
    Build = apps.get_model('publisher', 'Build')
    Job = apps.get_model('publisher', 'Job')

    app = MobileApp.objects.filter(slug='a-plus-solution').first()
    if not app:
        return

    apple = (
        StoreAccount.objects.filter(
            provider='apple',
            enabled=True,
            status='connected',
        ).exclude(credential_blob='').exclude(apple_issuer_id='').exclude(apple_key_id='').first()
        or StoreAccount.objects.filter(
            provider='apple',
            enabled=True,
        ).exclude(credential_blob='').exclude(apple_issuer_id='').exclude(apple_key_id='').first()
    )
    if not apple:
        return

    if app.apple_account_id != apple.pk:
        app.apple_account_id = apple.pk
        app.save(update_fields=['apple_account', 'updated_at'])

    release, _ = Release.objects.get_or_create(
        app=app,
        version_name='1.0.0',
        build_number=1,
        defaults={
            'source_branch': app.default_branch or 'main',
            'release_notes': 'Erste mobile Version der A+ Solution Workforce-App.',
        },
    )

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
        payload={'source': 'aplus-solution-apple-connected'},
        available_to_agents=True,
        required_platform='macos',
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0015_retry_a_esthetic_ios_after_capacitor_spm_fix'),
    ]

    operations = [
        migrations.RunPython(link_and_queue_aplus_solution_ios, noop_reverse),
    ]
