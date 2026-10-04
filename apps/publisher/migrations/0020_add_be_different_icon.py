from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import migrations


def add_be_different_icon(apps, schema_editor):
    MobileApp = apps.get_model("publisher", "MobileApp")
    AppAsset = apps.get_model("publisher", "AppAsset")
    app = MobileApp.objects.filter(slug="be-different").first()
    if not app:
        return
    source = Path(settings.BASE_DIR) / "apps" / "publisher" / "bootstrap_assets" / "be-different-icon.png"
    if not source.exists():
        raise RuntimeError(f"BE DIFFERENT bootstrap icon missing: {source}")
    asset, _ = AppAsset.objects.get_or_create(
        app=app,
        kind="icon",
        platform="shared",
        locale="de-DE",
        defaults={"device_type": "", "sort_order": 0, "width": 1254, "height": 1254},
    )
    if asset.file:
        return
    with source.open("rb") as handle:
        asset.file.save("be-different-icon.png", File(handle), save=False)
    asset.device_type = ""
    asset.sort_order = 0
    asset.width = 1254
    asset.height = 1254
    asset.save()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("publisher", "0019_queue_aplus_solution_keyboard_fix_release"),
    ]

    operations = [
        migrations.RunPython(add_be_different_icon, noop_reverse),
    ]
