# Generated for A+ Publisher Google Play compliance automation.
import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("publisher", "0005_mobileapp_android_signing"),
    ]

    operations = [
        migrations.CreateModel(
            name="ComplianceProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("analyzing", "Analyzing"), ("generated", "Generated"), ("needs_review", "Needs review"), ("ready", "Ready"), ("partially_applied", "Partially applied"), ("applied", "Applied"), ("failed", "Failed")], default="draft", max_length=30)),
                ("primary_locale", models.CharField(default="de-DE", max_length=20)),
                ("support_email", models.EmailField(blank=True, max_length=254)),
                ("purpose", models.TextField(blank=True)),
                ("business_model", models.CharField(blank=True, max_length=120)),
                ("has_ads", models.BooleanField(default=False)),
                ("target_age_groups", models.JSONField(blank=True, default=list)),
                ("app_access", models.CharField(choices=[("unrestricted", "All functionality is available without access"), ("login", "Login or membership is required"), ("restricted", "Some functionality is otherwise restricted")], default="unrestricted", max_length=30)),
                ("app_access_instructions", models.TextField(blank=True)),
                ("source_analysis", models.JSONField(blank=True, default=dict)),
                ("data_practices", models.JSONField(blank=True, default=dict)),
                ("content_rating_answers", models.JSONField(blank=True, default=dict)),
                ("store_declarations", models.JSONField(blank=True, default=dict)),
                ("generated_content", models.JSONField(blank=True, default=dict)),
                ("console_autofill", models.JSONField(blank=True, default=dict)),
                ("unresolved_questions", models.JSONField(blank=True, default=list)),
                ("privacy_policy_text", models.TextField(blank=True)),
                ("data_safety_csv", models.TextField(blank=True)),
                ("data_safety_template", models.FileField(blank=True, upload_to="compliance/data-safety-templates/")),
                ("confidence", models.DecimalField(decimal_places=3, default=0, max_digits=4)),
                ("ai_used", models.BooleanField(default=False)),
                ("ai_model", models.CharField(blank=True, max_length=100)),
                ("last_generated_at", models.DateTimeField(blank=True, null=True)),
                ("last_applied_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("companion_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("companion_token_expires_at", models.DateTimeField(blank=True, null=True)),
                ("app", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="compliance", to="publisher.mobileapp")),
            ],
            options={"ordering": ["app__name"]},
        ),
        migrations.CreateModel(
            name="ComplianceRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action", models.CharField(choices=[("analyze", "Analyze source"), ("generate", "Generate compliance pack"), ("apply", "Apply Google APIs"), ("companion", "Console companion")], max_length=30)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("partial", "Partial"), ("failed", "Failed")], default="queued", max_length=20)),
                ("progress", models.PositiveSmallIntegerField(default=0)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("logs", models.TextField(blank=True)),
                ("error", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="compliance.complianceprofile")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
