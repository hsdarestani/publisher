from django.db import migrations


def create_vice_codes_first_release(apps, schema_editor):
    """Idempotent draft release. No build jobs and no store submission."""
    MobileApp = apps.get_model("publisher", "MobileApp")
    Release = apps.get_model("publisher", "Release")
    Build = apps.get_model("publisher", "Build")

    app = MobileApp.objects.filter(slug="vice-codes").first()
    if app is None:
        return

    release, _created = Release.objects.get_or_create(
        app=app,
        version_name="1.0.0",
        build_number=1,
        defaults={
            "status": "draft",
            "source_branch": "main",
            "android_track": "internal",
            "android_rollout": 1,
            "ios_release_type": "manual",
            "auto_submit": False,
            "release_notes": "Erste Version des unabhängigen GTA-VI-Fan-Guides mit Offline-Suche und Favoriten.",
        },
    )
    for platform in ("android", "ios"):
        Build.objects.get_or_create(
            release=release,
            platform=platform,
            defaults={"status": "queued"},
        )


def keep_user_records_on_rollback(apps, schema_editor):
    # Once users begin building, do not remove their release history.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("publisher", "0021_create_vice_codes_setup"),
    ]

    operations = [
        migrations.RunPython(create_vice_codes_first_release, keep_user_records_on_rollback),
    ]
