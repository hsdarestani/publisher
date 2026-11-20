from django.db import migrations


def add_vice_codes_android_feature_graphic(apps, schema_editor):
    from io import BytesIO
    from django.core.files.base import ContentFile
    from PIL import Image, ImageDraw, ImageFont

    MobileApp = apps.get_model("publisher", "MobileApp")
    AppAsset = apps.get_model("publisher", "AppAsset")
    app = MobileApp.objects.filter(slug="vice-codes").first()
    if not app or AppAsset.objects.filter(app=app, kind="feature_graphic", platform="android").exists():
        return

    w, h = 1024, 500
    pic = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(pic)
    for y in range(h):
        f = y / h
        draw.line((0, y, w, y), fill=(int(26 + 40*f), int(15 + 22*f), int(44 + 20*f)))
    draw.ellipse((650, 55, 960, 365), fill=(245, 141, 142))
    draw.rectangle((0, 395, w, 500), fill=(25, 19, 39))
    # Original palm silhouette, not a game asset, logo or trademark.
    dark = (29, 18, 42)
    draw.line([(784, 421), (790, 310), (824, 188)], fill=dark, width=24)
    for end in [(660,170),(705,110),(790,100),(920,140),(981,229),(916,310),(686,279)]:
        draw.line([(822, 190), end], fill=dark, width=19)
    fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    def font(size):
        for location in fonts:
            try:
                return ImageFont.truetype(location, size)
            except OSError:
                continue
        return ImageFont.load_default()
    draw.text((64, 154), "VICE", font=font(97), fill=(254, 244, 237))
    draw.text((64, 258), "CODES", font=font(97), fill=(255, 189, 159))
    draw.text((68, 379), "DEUTSCHER OFFLINE-GUIDE", font=font(25), fill=(255, 205, 200))
    buffer = BytesIO()
    pic.save(buffer, format="PNG", optimize=True)
    asset = AppAsset(
        app=app, kind="feature_graphic", platform="android",
        locale="de-DE", width=w, height=h, sort_order=0,
    )
    asset.file.save("vice-codes-original-feature-1024x500.png", ContentFile(buffer.getvalue()), save=False)
    asset.save()


def preserve_on_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("publisher", "0024_vice_codes_privacy_support_store_metadata")]
    operations = [migrations.RunPython(add_vice_codes_android_feature_graphic, preserve_on_reverse)]
