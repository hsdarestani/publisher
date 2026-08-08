from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("publisher", "0015_retry_a_esthetic_ios_after_capacitor_spm_fix"),
        ("signing", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="IOSDistributionCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("credential_blob", models.TextField()),
                ("apple_certificate_id", models.CharField(max_length=120, unique=True)),
                ("certificate_serial_number", models.CharField(blank=True, max_length=160)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("generated_automatically", models.BooleanField(default=True)),
                ("store_account", models.OneToOneField(limit_choices_to={"provider": "apple"}, on_delete=django.db.models.deletion.CASCADE, related_name="ios_distribution_signing", to="publisher.storeaccount")),
            ],
            options={"ordering": ["store_account__name"]},
        ),
        migrations.CreateModel(
            name="IOSProvisioningProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("credential_blob", models.TextField()),
                ("apple_profile_id", models.CharField(max_length=120, unique=True)),
                ("profile_name", models.CharField(max_length=240)),
                ("profile_uuid", models.CharField(blank=True, max_length=120)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("app", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ios_provisioning_profile", to="publisher.mobileapp")),
                ("distribution_credential", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="profiles", to="signing.iosdistributioncredential")),
            ],
            options={"ordering": ["app__name"]},
        ),
    ]
