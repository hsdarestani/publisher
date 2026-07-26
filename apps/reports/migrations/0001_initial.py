from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("publisher", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="MetricPoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("store", models.CharField(choices=[("google", "Google Play"), ("apple", "App Store"), ("github", "GitHub"), ("internal", "Internal")], max_length=20)),
                ("date", models.DateField()), ("metric", models.CharField(max_length=80)), ("value", models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                ("dimensions", models.JSONField(blank=True, default=dict)), ("source", models.CharField(blank=True, max_length=160)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metrics", to="publisher.mobileapp")),
            ], options={"ordering": ["date"]},
        ),
        migrations.AddConstraint(model_name="metricpoint", constraint=models.UniqueConstraint(fields=("app", "store", "date", "metric", "dimensions"), name="unique_metric_point")),
        migrations.AddIndex(model_name="metricpoint", index=models.Index(fields=["app", "metric", "date"], name="reports_met_app_id_60ee00_idx")),
        migrations.AddIndex(model_name="metricpoint", index=models.Index(fields=["store", "date"], name="reports_met_store_29f0c7_idx")),
        migrations.CreateModel(
            name="TechnicalIssue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("store", models.CharField(choices=[("google", "Google Play"), ("apple", "App Store"), ("internal", "Internal")], max_length=20)),
                ("external_id", models.CharField(blank=True, max_length=180)), ("fingerprint", models.CharField(max_length=180)), ("issue_type", models.CharField(max_length=80)),
                ("title", models.CharField(max_length=300)), ("severity", models.CharField(choices=[("critical", "Critical"), ("high", "High"), ("medium", "Medium"), ("low", "Low")], default="medium", max_length=20)),
                ("status", models.CharField(choices=[("open", "Open"), ("investigating", "Investigating"), ("resolved", "Resolved"), ("ignored", "Ignored")], default="open", max_length=20)),
                ("occurrences", models.PositiveIntegerField(default=0)), ("affected_users", models.PositiveIntegerField(default=0)), ("first_seen", models.DateTimeField(blank=True, null=True)), ("last_seen", models.DateTimeField(blank=True, null=True)),
                ("app_version", models.CharField(blank=True, max_length=80)), ("os_version", models.CharField(blank=True, max_length=80)), ("device", models.CharField(blank=True, max_length=160)),
                ("stack_trace", models.TextField(blank=True)), ("raw", models.JSONField(blank=True, default=dict)),
                ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="technical_issues", to="publisher.mobileapp")),
            ], options={"ordering": ["-last_seen", "-updated_at"]},
        ),
        migrations.AddConstraint(model_name="technicalissue", constraint=models.UniqueConstraint(fields=("app", "store", "fingerprint"), name="unique_technical_issue")),
        migrations.AddIndex(model_name="technicalissue", index=models.Index(fields=["app", "status", "severity"], name="reports_tec_app_id_4c2097_idx")),
        migrations.CreateModel(
            name="RepositorySnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("commit_sha", models.CharField(max_length=64)), ("branch", models.CharField(max_length=120)), ("commit_count", models.PositiveIntegerField(default=0)),
                ("contributors", models.JSONField(blank=True, default=list)), ("languages", models.JSONField(blank=True, default=dict)), ("stack", models.JSONField(blank=True, default=list)), ("commits", models.JSONField(blank=True, default=list)),
                ("captured_at", models.DateTimeField(auto_now_add=True)), ("app", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="repository_snapshots", to="publisher.mobileapp")),
            ], options={"ordering": ["-captured_at"]},
        ),
        migrations.CreateModel(
            name="ReportSync",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(max_length=30)), ("status", models.CharField(default="running", max_length=20)), ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)), ("rows_imported", models.PositiveIntegerField(default=0)), ("error", models.TextField(blank=True)), ("metadata", models.JSONField(blank=True, default=dict)),
                ("app", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="report_syncs", to="publisher.mobileapp")),
            ],
        ),
    ]
