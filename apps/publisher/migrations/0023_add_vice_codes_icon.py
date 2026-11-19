from django.db import migrations


def add_original_vice_codes_icon(apps, schema_editor):
    """Add an original 1024px store icon only when this app has no icon."""
    import hashlib
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image, ImageDraw

    MobileApp = apps.get_model("publisher", "MobileApp")
    AppAsset = apps.get_model("publisher", "AppAsset")
    app = MobileApp.objects.filter(slug="vice-codes").first()
    if app is None or AppAsset.objects.filter(app=app, kind="icon").exists():
        return

    width = 1024
    image = Image.new("RGB", (width, width))
    painter = ImageDraw.Draw(image)
    for y in range(width):
        t = y / (width - 1)
        color = (int(28 + 82 * t), int(16 + 30 * t), int(44 + 21 * t))
        painter.line((0, y, width, y), fill=color)
    # Original Leonida-inspired sunset / silhouette — no third-party artwork.
    painter.ellipse((390, 118, 952, 680), fill=(249, 158, 149))
    painter.ellipse((465, 196, 878, 608), fill=(254, 192, 152))
    # Atmospheric horizon and a bold palm-tree mark.
    painter.polygon([(0, 760), (270, 722), (545, 776), (740, 741), (1024, 787),
                    (1024, 1024), (0, 1024)], fill=(27, 19, 40))
    trunk = [(350, 835), (380, 623), (421, 438), (448, 445), (414, 639), (397, 846)]
    painter.polygon(trunk, fill=(31, 20, 45))
    dark = (31, 20, 45)
    leaves = [
        [(441, 445), (265, 310), (146, 361), (281, 353), (351, 389)],
        [(441, 445), (320, 230), (196, 220), (307, 277), (388, 386)],
        [(441, 445), (455, 186), (376, 161), (427, 258), (429, 386)],
        [(441, 445), (608, 246), (670, 285), (557, 294), (481, 385)],
        [(441, 445), (735, 380), (783, 490), (663, 414), (517, 416)],
        [(441, 445), (627, 540), (600, 637), (554, 557), (487, 472)],
        [(441, 445), (215, 481), (153, 593), (287, 514), (380, 450)],
    ]
    for leaf in leaves:
        painter.polygon(leaf, fill=dark)
    # Minimal geometric VI hallmark distinct from any Rockstar trademark.
    painter.line([(660, 762), (747, 916), (834, 762)], fill=(254, 190, 157), width=24)
    painter.line([(865, 769), (865, 907)], fill=(254, 190, 157), width=22)

    stream = BytesIO()
    image.save(stream, format="PNG", optimize=True)
    payload = stream.getvalue()
    asset = AppAsset(
        app=app,
        kind="icon",
        platform="shared",
        locale="de-DE",
        device_type="",
        sort_order=0,
        width=width,
        height=width,
        checksum=hashlib.sha256(payload).hexdigest(),
    )
    asset.file.save("vice-codes-original-1024.png", ContentFile(payload), save=False)
    asset.save()


def preserve_assets_on_rollback(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("publisher", "0022_create_vice_codes_initial_release")]
    operations = [
        migrations.RunPython(add_original_vice_codes_icon, preserve_assets_on_rollback),
    ]
