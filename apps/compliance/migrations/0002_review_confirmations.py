from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("compliance", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="complianceprofile",
            name="account_deletion",
            field=models.CharField(
                choices=[
                    ("unknown", "Not confirmed yet"),
                    ("in_app", "Users can delete their account inside the app"),
                    ("web", "Users can request deletion on a public web page"),
                    ("support", "Users can request deletion through support"),
                    ("unavailable", "Account deletion is not available yet"),
                    ("not_applicable", "The app does not create user accounts"),
                ],
                default="unknown",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="complianceprofile",
            name="account_deletion_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="complianceprofile",
            name="payment_details",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="complianceprofile",
            name="payment_handling",
            field=models.CharField(
                choices=[
                    ("unknown", "Not confirmed yet"),
                    ("none", "The app does not process payments"),
                    ("external", "Payments are handled by an external provider"),
                    ("direct", "The app or backend directly handles payment data"),
                ],
                default="unknown",
                max_length=30,
            ),
        ),
    ]
