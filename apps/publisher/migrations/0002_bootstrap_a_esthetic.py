from django.db import migrations


def bootstrap_a_esthetic(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    AppLocalization = apps.get_model('publisher', 'AppLocalization')

    app, _ = MobileApp.objects.get_or_create(
        slug='a-esthetic',
        defaults={
            'name': 'A+ Esthetic',
            'client_name': 'A+ Esthetic GmbH',
        },
    )

    # Keep store-account assignments, reviewer secrets and external IDs untouched
    # if an operator already configured them. These fields are safe/idempotent.
    app.name = 'A+ Esthetic'
    app.client_name = 'A+ Esthetic GmbH'
    app.platform = 'both'
    app.framework = 'other'
    if app.status == 'archived':
        app.status = 'setup'
    app.package_name = 'de.aplusesthetic.app'
    app.bundle_id = 'de.aplusesthetic.app'
    app.repository_url = 'https://github.com/hsdarestani/a_esthetic'
    app.default_branch = 'main'
    app.privacy_policy_url = 'https://esthetic.smarbiz.sbs/datenschutz/'
    app.support_url = 'https://esthetic.smarbiz.sbs/support/'
    app.marketing_url = 'https://a-esthetic.de/'
    app.category = 'Lifestyle'
    app.requires_login = True
    app.build_config = {
        'android_command': 'REQUIRE_ANDROID_SIGNING=1 bash scripts/build-android.sh',
        'android_artifact': 'artifacts/a-esthetic-release.aab',
        'ios_command': 'bash scripts/build-ios.sh',
        'ios_artifact': 'artifacts/a-esthetic.ipa',
        'env': {},
    }
    app.tech_stack = ['Capacitor 8', 'Django', 'Customer Club API']
    app.save()

    AppLocalization.objects.update_or_create(
        app=app,
        locale='de-DE',
        defaults={
            'title': 'A+ Esthetic',
            'subtitle': 'Ihr digitaler Kundenclub',
            'short_description': 'Mitgliedschaft, Vorteile, Rewards, Termine und A+ Coins an einem Ort.',
            'full_description': (
                'A+ Esthetic ist Ihr digitaler Kundenclub. Verwalten Sie Ihre Mitgliedschaft, '
                'entdecken Sie Club-Vorteile und Rewards, behalten Sie A+ Coins und Club-Guthaben '
                'im Blick und senden Sie organisatorische Terminanfragen direkt aus der App.\n\n'
                'Außerdem erhalten Sie Erinnerungen, aktuelle Club-Aktionen und können den '
                'A+ Esthetic Kundenservice direkt erreichen.\n\n'
                'Die App konzentriert sich ausschließlich auf Kundenclub, Loyalty, Organisation '
                'und Service.'
            ),
            'keywords': 'Beauty Club,Kundenclub,Loyalty,Rewards,Termine,Coins,Frankfurt',
            'promotional_text': 'Ihre A+ Vorteile, Rewards und Termine in einer App.',
            'release_notes': 'Erste Version des A+ Esthetic Kundenclubs.',
        },
    )


def noop_reverse(apps, schema_editor):
    # Do not remove a production app record on migration rollback.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(bootstrap_a_esthetic, noop_reverse),
    ]
