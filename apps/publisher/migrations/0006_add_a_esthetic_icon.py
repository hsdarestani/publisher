from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import migrations


ICON_CHECKSUM = '7c2a446ab3ec21ec94380e41c0f6ade8d44f75f018b93204158183e76e81d595'


def add_a_esthetic_icon(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    AppAsset = apps.get_model('publisher', 'AppAsset')

    app = MobileApp.objects.filter(slug='a-esthetic').first()
    if not app:
        return

    asset, _ = AppAsset.objects.get_or_create(
        app=app,
        kind='icon',
        platform='shared',
        locale='de-DE',
        defaults={
            'device_type': '',
            'sort_order': 0,
            'width': 512,
            'height': 512,
        },
    )

    source = Path(settings.BASE_DIR) / 'apps' / 'publisher' / 'bootstrap_assets' / 'a-esthetic-icon-512.png'
    if not source.exists():
        raise RuntimeError(f'A+ Esthetic bootstrap icon missing: {source}')

    # Avoid rewriting storage on later deploys once the intended asset exists.
    if asset.checksum == ICON_CHECKSUM and asset.file:
        return

    with source.open('rb') as handle:
        asset.file.save('a-esthetic-icon-512.png', File(handle), save=False)
    asset.device_type = ''
    asset.sort_order = 0
    asset.width = 512
    asset.height = 512
    asset.checksum = ICON_CHECKSUM
    asset.save()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0005_retry_a_esthetic_android_build'),
    ]

    operations = [
        migrations.RunPython(add_a_esthetic_icon, noop_reverse),
    ]
