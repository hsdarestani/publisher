from django.db import models
from apps.core.models import TimeStampedModel
from apps.publisher.models import MobileApp

class MetricPoint(TimeStampedModel):
    STORES = [("google", "Google Play"), ("apple", "App Store"), ("github", "GitHub"), ("internal", "Internal")]
    app = models.ForeignKey(MobileApp, related_name="metrics", on_delete=models.CASCADE)
    store = models.CharField(max_length=20, choices=STORES)
    date = models.DateField()
    metric = models.CharField(max_length=80)
    value = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    dimensions = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["app", "store", "date", "metric", "dimensions"], name="unique_metric_point")]
        indexes = [models.Index(fields=["app", "metric", "date"]), models.Index(fields=["store", "date"])]

    def __str__(self):
        return f"{self.app} {self.metric} {self.date}"

class TechnicalIssue(TimeStampedModel):
    STORES = [("google", "Google Play"), ("apple", "App Store"), ("internal", "Internal")]
    SEVERITIES = [("critical", "Critical"), ("high", "High"), ("medium", "Medium"), ("low", "Low")]
    STATUSES = [("open", "Open"), ("investigating", "Investigating"), ("resolved", "Resolved"), ("ignored", "Ignored")]
    app = models.ForeignKey(MobileApp, related_name="technical_issues", on_delete=models.CASCADE)
    store = models.CharField(max_length=20, choices=STORES)
    external_id = models.CharField(max_length=180, blank=True)
    fingerprint = models.CharField(max_length=180)
    issue_type = models.CharField(max_length=80)
    title = models.CharField(max_length=300)
    severity = models.CharField(max_length=20, choices=SEVERITIES, default="medium")
    status = models.CharField(max_length=20, choices=STATUSES, default="open")
    occurrences = models.PositiveIntegerField(default=0)
    affected_users = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    app_version = models.CharField(max_length=80, blank=True)
    os_version = models.CharField(max_length=80, blank=True)
    device = models.CharField(max_length=160, blank=True)
    stack_trace = models.TextField(blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_seen", "-updated_at"]
        constraints = [models.UniqueConstraint(fields=["app", "store", "fingerprint"], name="unique_technical_issue")]
        indexes = [models.Index(fields=["app", "status", "severity"])]

    def __str__(self):
        return self.title

class RepositorySnapshot(TimeStampedModel):
    app = models.ForeignKey(MobileApp, related_name="repository_snapshots", on_delete=models.CASCADE)
    commit_sha = models.CharField(max_length=64)
    branch = models.CharField(max_length=120)
    commit_count = models.PositiveIntegerField(default=0)
    contributors = models.JSONField(default=list, blank=True)
    languages = models.JSONField(default=dict, blank=True)
    stack = models.JSONField(default=list, blank=True)
    commits = models.JSONField(default=list, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-captured_at"]

class ReportSync(TimeStampedModel):
    app = models.ForeignKey(MobileApp, null=True, blank=True, related_name="report_syncs", on_delete=models.CASCADE)
    provider = models.CharField(max_length=30)
    status = models.CharField(max_length=20, default="running")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    rows_imported = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
