from django.db import migrations


def create_vice_codes_setup(apps, schema_editor):
    """Register the new GTA VI guide without publishing or triggering a build."""
    MobileApp = apps.get_model("publisher", "MobileApp")
    AppLocalization = apps.get_model("publisher", "AppLocalization")
    config = {
        "android_command": "bash mobile/scripts/build-android.sh",
        "android_artifact": "mobile/build/app/outputs/bundle/release/*.aab",
        "ios_command": "bash mobile/scripts/build-ios.sh",
        "ios_artifact": "mobile/build/ios/ipa/*.ipa",
        "env": {},
    }
    app, created = MobileApp.objects.get_or_create(
        slug="vice-codes",
        defaults={
            "name": "Vice Codes",
            "client_name": "",
            "platform": "both",
            "framework": "flutter",
            "status": "setup",
            "package_name": "de.smarbiz.vicecodes",
            "bundle_id": "de.smarbiz.vicecodes",
            "repository_url": "https://github.com/hsdarestani/gtacheat",
            "default_branch": "main",
            "support_url": "https://gta.smarbiz.sbs/",
            "marketing_url": "https://gta.smarbiz.sbs/",
            "privacy_policy_url": "",
            "category": "Entertainment",
            "requires_login": False,
            "build_config": config,
            "tech_stack": ["Flutter", "Offline JSON", "SharedPreferences"],
        },
    )
    if not created:
        # Existing app wins: never overwrite user edits or link accounts implicitly.
        return
    AppLocalization.objects.get_or_create(
        app=app,
        locale="de-DE",
        defaults={
            "title": "Vice Codes – GTA VI Guide",
            "subtitle": "Cheats für PS5 und Xbox",
            "short_description": "Inoffizieller GTA-VI-Guide mit 19 Codes, Offline-Suche und Favoriten.",
            "full_description": (
                "Vice Codes ist ein unabhängiger, deutschsprachiger Fan-Guide für GTA VI.\n\n"
                "• 19 veröffentlichte Tastenkombinationen für PS5 und Xbox Series X|S\n"
                "• Offline-Suche und Kategorien\n"
                "• Freischaltbedingungen pro Code\n"
                "• Merkliste, Fortschritt und Kopieren/Teilen\n"
                "• Alle Favoriten bleiben nur auf deinem Gerät.\n\n"
                "Die Eingaben wurden aus journalistischen Guides übernommen "
                "und nicht von uns im Spiel getestet.\n"
                "Keine Verbindung zu Rockstar Games oder Take-Two Interactive."
            ),
            "keywords": "GTA 6,Cheats,Codes,PS5,Xbox,Leonida,Fan Guide",
            "promotional_text": "19 GTA-VI-Codes offline finden und merken.",
            "release_notes": "Erste Fassung der deutschsprachigen Offline-Cheat-App.",
        },
    )


def preserve_on_reverse(apps, schema_editor):
    # Removing a migration must not delete a possibly live app or user changes.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("publisher", "0020_add_be_different_icon"),
    ]

    operations = [
        migrations.RunPython(create_vice_codes_setup, preserve_on_reverse),
    ]
