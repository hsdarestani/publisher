from django.db import migrations, models
import django.db.models.deletion
import apps.publisher.models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="StoreAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(choices=[("google", "Google Play"), ("apple", "Apple App Store")], max_length=20)),
                ("name", models.CharField(max_length=120)), ("organization", models.CharField(blank=True, max_length=160)),
                ("enabled", models.BooleanField(default=True)), ("status", models.CharField(default="not_configured", max_length=30)),
                ("credential_blob", models.TextField(blank=True)), ("google_bucket_id", models.CharField(blank=True, max_length=180)),
                ("apple_issuer_id", models.CharField(blank=True, max_length=120)), ("apple_key_id", models.CharField(blank=True, max_length=80)),
                ("apple_team_id", models.CharField(blank=True, max_length=80)), ("apple_vendor_number", models.CharField(blank=True, max_length=80)),
                ("last_tested_at", models.DateTimeField(blank=True, null=True)), ("last_error", models.TextField(blank=True)),
            ], options={"ordering": ["provider", "name"]},
        ),
        migrations.AddConstraint(model_name="storeaccount", constraint=models.UniqueConstraint(fields=("provider", "name"), name="unique_store_account")),
        migrations.CreateModel(
            name="MobileApp",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=160)), ("slug", models.SlugField(unique=True)), ("client_name", models.CharField(blank=True, max_length=160)),
                ("platform", models.CharField(choices=[("both", "Android + iOS"), ("android", "Android"), ("ios", "iOS")], default="both", max_length=20)),
                ("framework", models.CharField(choices=[("flutter", "Flutter"), ("react_native", "React Native"), ("native", "Native"), ("other", "Other")], default="flutter", max_length=30)),
                ("status", models.CharField(choices=[("setup", "Setup"), ("active", "Active"), ("paused", "Paused"), ("archived", "Archived")], default="setup", max_length=20)),
                ("package_name", models.CharField(blank=True, max_length=180)), ("bundle_id", models.CharField(blank=True, max_length=180)),
                ("google_app_id", models.CharField(blank=True, max_length=120)), ("apple_app_id", models.CharField(blank=True, max_length=120)),
                ("repository_url", models.URLField(blank=True)), ("default_branch", models.CharField(default="main", max_length=120)), ("repository_token_blob", models.TextField(blank=True)),
                ("privacy_policy_url", models.URLField(blank=True)), ("support_url", models.URLField(blank=True)), ("marketing_url", models.URLField(blank=True)),
                ("category", models.CharField(blank=True, max_length=120)), ("content_rating", models.CharField(blank=True, max_length=120)),
                ("requires_login", models.BooleanField(default=False)), ("review_username", models.CharField(blank=True, max_length=180)), ("review_password_blob", models.TextField(blank=True)), ("review_notes", models.TextField(blank=True)),
                ("build_config", models.JSONField(blank=True, default=dict, help_text="Optional build commands, artifact globs, scheme/workspace and environment overrides.")),
                ("tech_stack", models.JSONField(blank=True, default=list)), ("latest_commit_sha", models.CharField(blank=True, max_length=64)),
                ("latest_commit_at", models.DateTimeField(blank=True, null=True)), ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("apple_account", models.ForeignKey(blank=True, limit_choices_to={"provider": "apple"}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="apple_apps", to="publisher.storeaccount")),
                ("google_account", models.ForeignKey(blank=True, limit_choices_to={"provider": "google"}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="google_apps", to="publisher.storeaccount")),
            ], options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="AppLocalization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("locale", models.CharField(default="en-US", max_length=20)), ("title", models.CharField(max_length=50)), ("subtitle", models.CharField(blank=True, max_length=50)),
                ("short_description", models.CharField(blank=True, max_length=80)), ("full_description", models.TextField(blank=True)), ("keywords", models.CharField(blank=True, max_length=100)),
                ("promotional_text", models.CharField(blank=True, max_length=170)), ("release_notes", models.TextField(blank=True)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="localizations", to="publisher.mobileapp")),
            ], options={"ordering": ["locale"]},
        ),
        migrations.AddConstraint(model_name="applocalization", constraint=models.UniqueConstraint(fields=("app", "locale"), name="unique_app_locale")),
        migrations.CreateModel(
            name="AppAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(choices=[("icon", "App icon"), ("screenshot", "Screenshot"), ("feature_graphic", "Feature graphic"), ("promo", "Promo graphic"), ("review_attachment", "Review attachment")], max_length=30)),
                ("platform", models.CharField(choices=[("shared", "Shared"), ("android", "Android"), ("ios", "iOS")], default="shared", max_length=20)),
                ("locale", models.CharField(default="en-US", max_length=20)), ("device_type", models.CharField(blank=True, max_length=80)),
                ("file", models.FileField(upload_to=apps.publisher.models.asset_upload_path)), ("sort_order", models.PositiveIntegerField(default=0)),
                ("checksum", models.CharField(blank=True, max_length=64)), ("width", models.PositiveIntegerField(blank=True, null=True)), ("height", models.PositiveIntegerField(blank=True, null=True)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assets", to="publisher.mobileapp")),
            ], options={"ordering": ["platform", "locale", "kind", "sort_order"]},
        ),
        migrations.CreateModel(
            name="Release",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("version_name", models.CharField(max_length=40)), ("build_number", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("draft", "Draft"), ("checking", "Checking"), ("ready", "Ready"), ("building", "Building"), ("uploaded", "Uploaded"), ("in_review", "In review"), ("approved", "Approved"), ("released", "Released"), ("rejected", "Rejected"), ("failed", "Failed")], default="draft", max_length=30)),
                ("source_branch", models.CharField(blank=True, max_length=120)), ("source_commit", models.CharField(blank=True, max_length=64)),
                ("android_track", models.CharField(default="internal", max_length=40)), ("android_rollout", models.DecimalField(decimal_places=4, default=1, max_digits=5)),
                ("ios_release_type", models.CharField(default="manual", max_length=40)), ("auto_submit", models.BooleanField(default=False)),
                ("release_notes", models.TextField(blank=True)), ("readiness_snapshot", models.JSONField(blank=True, default=dict)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)), ("released_at", models.DateTimeField(blank=True, null=True)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="releases", to="publisher.mobileapp")),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(model_name="release", constraint=models.UniqueConstraint(fields=("app", "version_name", "build_number"), name="unique_release_build")),
        migrations.CreateModel(
            name="BuildAgent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120, unique=True)), ("platform", models.CharField(choices=[("linux", "Linux / Android"), ("macos", "macOS / iOS"), ("universal", "Universal")], max_length=20)),
                ("enabled", models.BooleanField(default=True)), ("token_hash", models.CharField(max_length=64, unique=True)), ("labels", models.JSONField(blank=True, default=list)),
                ("capabilities", models.JSONField(blank=True, default=dict)), ("hostname", models.CharField(blank=True, max_length=180)), ("app_version", models.CharField(blank=True, max_length=40)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
            ], options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Build",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("platform", models.CharField(choices=[("android", "Android"), ("ios", "iOS")], max_length=20)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("claimed", "Claimed"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("cancelled", "Cancelled")], default="queued", max_length=20)),
                ("commit_sha", models.CharField(blank=True, max_length=64)), ("artifact", models.FileField(blank=True, upload_to="builds/%Y/%m/")),
                ("artifact_size", models.BigIntegerField(default=0)), ("artifact_checksum", models.CharField(blank=True, max_length=64)), ("logs", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)), ("finished_at", models.DateTimeField(blank=True, null=True)), ("external_build_id", models.CharField(blank=True, max_length=160)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("agent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="builds", to="publisher.buildagent")),
                ("release", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="builds", to="publisher.release")),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Job",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("type", models.CharField(choices=[("build_android", "Build Android"), ("build_ios", "Build iOS"), ("upload_google", "Upload Google Play"), ("upload_apple", "Upload App Store"), ("submit_google", "Submit Google review"), ("submit_apple", "Submit Apple review"), ("sync_google_reports", "Sync Google reports"), ("sync_apple_reports", "Sync Apple reports"), ("sync_store_status", "Sync store status"), ("sync_repository", "Sync repository")], max_length=40)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("cancelled", "Cancelled")], default="queued", max_length=20)),
                ("progress", models.PositiveSmallIntegerField(default=0)), ("payload", models.JSONField(blank=True, default=dict)), ("result", models.JSONField(blank=True, default=dict)),
                ("logs", models.TextField(blank=True)), ("error", models.TextField(blank=True)), ("available_to_agents", models.BooleanField(default=False)), ("required_platform", models.CharField(blank=True, max_length=20)),
                ("started_at", models.DateTimeField(blank=True, null=True)), ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("app", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="jobs", to="publisher.mobileapp")),
                ("build", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="jobs", to="publisher.build")),
                ("release", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="jobs", to="publisher.release")),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.AddField(model_name="buildagent", name="current_job", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_agents", to="publisher.job")),
        migrations.CreateModel(
            name="Submission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("platform", models.CharField(choices=[("android", "Google Play"), ("ios", "App Store")], max_length=20)), ("state", models.CharField(default="not_submitted", max_length=60)),
                ("external_id", models.CharField(blank=True, max_length=160)), ("store_url", models.URLField(blank=True)), ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)), ("last_error", models.TextField(blank=True)), ("raw", models.JSONField(blank=True, default=dict)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="publisher.mobileapp")),
                ("release", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="publisher.release")),
            ], options={"ordering": ["-updated_at"]},
        ),
        migrations.AddConstraint(model_name="submission", constraint=models.UniqueConstraint(fields=("release", "platform"), name="unique_release_submission")),
    ]
