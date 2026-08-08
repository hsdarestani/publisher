from django.db import migrations


def link_unambiguous_accounts(apps, schema_editor):
    MobileApp = apps.get_model('publisher', 'MobileApp')
    StoreAccount = apps.get_model('publisher', 'StoreAccount')

    app = MobileApp.objects.filter(slug='a-esthetic').first()
    if not app:
        return

    if not app.google_account_id:
        google = list(
            StoreAccount.objects.filter(provider='google', enabled=True)
            .exclude(credential_blob='')[:2]
        )
        if len(google) == 1:
            app.google_account_id = google[0].pk

    if not app.apple_account_id:
        apple = list(
            StoreAccount.objects.filter(provider='apple', enabled=True)
            .exclude(credential_blob='')
            .exclude(apple_issuer_id='')
            .exclude(apple_key_id='')[:2]
        )
        if len(apple) == 1:
            app.apple_account_id = apple[0].pk

    app.save(update_fields=['google_account', 'apple_account', 'updated_at'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('publisher', '0006_add_a_esthetic_icon'),
    ]

    operations = [
        migrations.RunPython(link_unambiguous_accounts, noop_reverse),
    ]
