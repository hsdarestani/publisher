from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("publisher", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AndroidSigningCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("credential_blob", models.TextField()),
                ("certificate_sha256", models.CharField(blank=True, max_length=128)),
                ("generated_automatically", models.BooleanField(default=True)),
                ("app", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="android_signing", to="publisher.mobileapp")),
            ],
            options={"ordering": ["app__name"]},
        ),
    ]
