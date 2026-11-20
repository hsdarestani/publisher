from django.db import migrations


def configure_vice_codes_store_readiness(apps, schema_editor):
    MobileApp = apps.get_model("publisher", "MobileApp")
    AppLocalization = apps.get_model("publisher", "AppLocalization")
    app = MobileApp.objects.filter(slug="vice-codes").first()
    if app is None:
        return

    changed_fields = []
    if not app.privacy_policy_url:
        app.privacy_policy_url = "https://gta.smarbiz.sbs/privacy"
        changed_fields.append("privacy_policy_url")
    if not app.support_url or app.support_url.rstrip("/") == "https://gta.smarbiz.sbs":
        app.support_url = "https://gta.smarbiz.sbs/support"
        changed_fields.append("support_url")
    if not app.review_notes:
        app.review_notes = (
            "Vice Codes ist ein unabhängiger, deutschsprachiger Offline-Fan-Guide "
            "für GTA VI. Die App ist keine offizielle Rockstar- oder Take-Two-App, "
            "benötigt keine Anmeldung und enthält keine Käufe oder Werbung. "
            "Favoriten und Fortschritt werden lokal auf dem Gerät gespeichert. "
            "Codes stammen aus veröffentlichten Spiele-Guides, nicht aus einem "
            "offiziellen Rockstar-Datensatz. Bitte die Offline-Suche, Kategorien, "
            "Detailansicht, Favoriten und Copy/Share testen."
        )
        changed_fields.append("review_notes")
    if changed_fields:
        app.save(update_fields=changed_fields + ["updated_at"])

    loc = AppLocalization.objects.filter(app=app, locale="de-DE").first()
    if loc is None:
        return
    edits = []
    # Do not overwrite any user's newer custom metadata.
    if loc.title == "Vice Codes – GTA VI Guide":
        loc.title = "Vice Codes – Spielhilfe"
        edits.append("title")
    if loc.subtitle == "Cheats für PS5 und Xbox":
        loc.subtitle = "Codes offline nachschlagen"
        edits.append("subtitle")
    if edits:
        loc.save(update_fields=edits + ["updated_at"])


def preserve_on_reverse(apps, schema_editor):
    # Published legal metadata and later user edits must never be removed.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("publisher", "0023_add_vice_codes_icon"),
    ]

    operations = [
        migrations.RunPython(configure_vice_codes_store_readiness, preserve_on_reverse),
    ]
