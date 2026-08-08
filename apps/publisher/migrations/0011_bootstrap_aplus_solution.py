from django.db import migrations


def bootstrap_aplus_solution(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    AppLocalization = apps.get_model('publisher', 'AppLocalization')
    StoreAccount = apps.get_model('publisher', 'StoreAccount')

    google_account = (
        StoreAccount.objects.filter(provider='google', name='A+ Solution Google Play').first()
        or StoreAccount.objects.filter(provider='google').order_by('id').first()
    )

    app, _ = MobileApp.objects.get_or_create(
        slug='a-plus-solution',
        defaults={
            'name': 'A+ Solution',
            'client_name': 'A+ Solution GmbH',
        },
    )

    app.name = 'A+ Solution'
    app.client_name = 'A+ Solution GmbH'
    app.platform = 'both'
    app.framework = 'other'
    app.status = 'active'
    app.package_name = 'de.aplussolution.workforce'
    app.bundle_id = 'de.aplussolution.workforce'
    app.repository_url = 'https://github.com/hsdarestani/aplussolution'
    app.default_branch = 'main'
    app.privacy_policy_url = 'https://solution.smarbiz.sbs/datenschutz'
    app.support_url = 'https://solution.smarbiz.sbs/support'
    app.marketing_url = 'https://solution.smarbiz.sbs/'
    app.category = 'Business'
    app.requires_login = True
    app.review_username = app.review_username or 'store-review@aplus-solution.de'
    app.review_notes = (
        'A+ Solution is the official workforce application of A+ Solution GmbH. '
        'There is no public self-registration; employee and management accounts are provisioned by the company. '
        'Use the dedicated review account configured in Publisher for store review. '
        'Location is requested only during active clock-in/out validation; no background location is used.'
    )
    app.google_account = google_account
    app.build_config = {
        'android_command': 'bash frontend/scripts/build-publisher-android.sh',
        'android_artifact': 'frontend/android/app/build/outputs/bundle/release/*.aab',
        'ios_command': 'bash frontend/scripts/build-publisher-ios.sh',
        'ios_artifact': 'frontend/ios/build/export/*.ipa',
        'env': {
            'VITE_API_URL': 'https://solution.smarbiz.sbs/api',
        },
    }
    app.tech_stack = ['Capacitor 7', 'React 19', 'Ionic React 8', 'Vite 7', 'Django API']
    app.save()

    AppLocalization.objects.update_or_create(
        app=app,
        locale='de-DE',
        defaults={
            'title': 'A+ Solution',
            'subtitle': 'Workforce-App für Ihr Team',
            'short_description': 'Interne Dienstplanung, Zeiterfassung und Dokumente für A+ Solution.',
            'full_description': (
                'A+ Solution ist die offizielle Workforce-App der A+ Solution GmbH für Mitarbeiter, '
                'Disposition und Management.\n\n'
                'Die App unterstützt zentrale interne Arbeitsabläufe wie Dienstplanung, '
                'Arbeitszeiterfassung, Verfügbarkeiten, Dokumente, interne Nachrichten und weitere '
                'organisatorische Prozesse.\n\n'
                'Funktionen im Überblick:\n'
                '• Dienstpläne und Schichten einsehen\n'
                '• Arbeitszeiten digital erfassen\n'
                '• Ein- und Ausstempeln bei Einsätzen\n'
                '• Verfügbarkeiten verwalten\n'
                '• Dokumente und Unterlagen abrufen\n'
                '• Interne Nachrichten nutzen\n'
                '• Anfragen und Korrekturen direkt über die App übermitteln\n\n'
                'Für standortgebundene Einsätze kann beim aktiven Ein- oder Ausstempeln der aktuelle '
                'Standort verwendet werden. Eine Hintergrundortung findet nicht statt.\n\n'
                'Die App kann öffentlich heruntergeladen werden. Die Nutzung der internen Funktionen '
                'ist ausschließlich für freigeschaltete Mitarbeiter und berechtigte Nutzer der '
                'A+ Solution GmbH möglich. Es gibt keine öffentliche Registrierung.'
            ),
            'keywords': 'Workforce,Dienstplan,Zeiterfassung,Mitarbeiter,Dokumente,Schichten',
            'promotional_text': 'Dienstplanung, Zeiterfassung und Dokumente in einer App.',
            'release_notes': 'Erste mobile Version der A+ Solution Workforce-App.',
        },
    )


def noop_reverse(apps, schema_editor):
    # Keep production app records intact on rollback.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0010_set_a_esthetic_review_login'),
    ]

    operations = [
        migrations.RunPython(bootstrap_aplus_solution, noop_reverse),
    ]
