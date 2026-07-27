import hashlib
import secrets
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from apps.core.crypto import encrypt_json, decrypt_json
from apps.core.models import TimeStampedModel

class StoreAccount(TimeStampedModel):
    PROVIDERS = [("google", "Google Play"), ("apple", "Apple App Store")]
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    name = models.CharField(max_length=120)
    organization = models.CharField(max_length=160, blank=True)
    enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=30, default="not_configured")
    credential_blob = models.TextField(blank=True)
    google_bucket_id = models.CharField(max_length=180, blank=True)
    apple_issuer_id = models.CharField(max_length=120, blank=True)
    apple_key_id = models.CharField(max_length=80, blank=True)
    apple_team_id = models.CharField(max_length=80, blank=True)
    apple_vendor_number = models.CharField(max_length=80, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["provider", "name"]
        constraints = [models.UniqueConstraint(fields=["provider", "name"], name="unique_store_account")]

    def __str__(self):
        return f"{self.get_provider_display()} · {self.name}"

    def set_credentials(self, value: dict):
        self.credential_blob = encrypt_json(value)

    def get_credentials(self) -> dict:
        return decrypt_json(self.credential_blob)

    @property
    def configured(self):
        if self.provider == "google":
            data = self.get_credentials()
            return bool(data.get("client_email") and data.get("private_key"))
        return bool(self.apple_issuer_id and self.apple_key_id and self.get_credentials().get("private_key"))

    @property
    def credential_identity(self):
        """Return a non-secret identity suitable for the UI and audit screens."""
        data = self.get_credentials()
        if self.provider == "google":
            return data.get("client_email", "")
        return self.apple_key_id or data.get("key_id", "")

    @property
    def credential_project_id(self):
        if self.provider != "google":
            return ""
        return self.get_credentials().get("project_id", "")

    @property
    def credential_type(self):
        data = self.get_credentials()
        if self.provider == "google":
            return data.get("type", "")
        return "App Store Connect API key" if data.get("private_key") else ""

class MobileApp(TimeStampedModel):
    PLATFORMS = [("both", "Android + iOS"), ("android", "Android"), ("ios", "iOS")]
    FRAMEWORKS = [("flutter", "Flutter"), ("react_native", "React Native"), ("native", "Native"), ("other", "Other")]
    STATUSES = [("setup", "Setup"), ("active", "Active"), ("paused", "Paused"), ("archived", "Archived")]
    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    client_name = models.CharField(max_length=160, blank=True)
    platform = models.CharField(max_length=20, choices=PLATFORMS, default="both")
    framework = models.CharField(max_length=30, choices=FRAMEWORKS, default="flutter")
    status = models.CharField(max_length=20, choices=STATUSES, default="setup")
    package_name = models.CharField(max_length=180, blank=True)
    bundle_id = models.CharField(max_length=180, blank=True)
    google_app_id = models.CharField(max_length=120, blank=True)
    apple_app_id = models.CharField(max_length=120, blank=True)
    repository_url = models.URLField(blank=True)
    default_branch = models.CharField(max_length=120, default="main")
    repository_token_blob = models.TextField(blank=True)
    privacy_policy_url = models.URLField(blank=True)
    support_url = models.URLField(blank=True)
    marketing_url = models.URLField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    content_rating = models.CharField(max_length=120, blank=True)
    requires_login = models.BooleanField(default=False)
    review_username = models.CharField(max_length=180, blank=True)
    review_password_blob = models.TextField(blank=True)
    review_notes = models.TextField(blank=True)
    google_account = models.ForeignKey(StoreAccount, null=True, blank=True, related_name="google_apps", limit_choices_to={"provider": "google"}, on_delete=models.SET_NULL)
    apple_account = models.ForeignKey(StoreAccount, null=True, blank=True, related_name="apple_apps", limit_choices_to={"provider": "apple"}, on_delete=models.SET_NULL)
    build_config = models.JSONField(default=dict, blank=True, help_text="Optional build commands, artifact globs, scheme/workspace and environment overrides.")
    tech_stack = models.JSONField(default=list, blank=True)
    latest_commit_sha = models.CharField(max_length=64, blank=True)
    latest_commit_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("app_detail", args=[self.pk])

    @property
    def supports_android(self):
        return self.platform in {"both", "android"}

    @property
    def supports_ios(self):
        return self.platform in {"both", "ios"}

    def set_repository_token(self, token: str):
        self.repository_token_blob = encrypt_json({"token": token}) if token else ""

    def get_repository_token(self):
        return decrypt_json(self.repository_token_blob).get("token", "")

    def set_review_password(self, password: str):
        self.review_password_blob = encrypt_json({"password": password}) if password else ""

    def get_review_password(self):
        return decrypt_json(self.review_password_blob).get("password", "")

class AppLocalization(TimeStampedModel):
    app = models.ForeignKey(MobileApp, related_name="localizations", on_delete=models.CASCADE)
    locale = models.CharField(max_length=20, default="en-US")
    title = models.CharField(max_length=50)
    subtitle = models.CharField(max_length=50, blank=True)
    short_description = models.CharField(max_length=80, blank=True)
    full_description = models.TextField(blank=True)
    keywords = models.CharField(max_length=100, blank=True)
    promotional_text = models.CharField(max_length=170, blank=True)
    release_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["locale"]
        constraints = [models.UniqueConstraint(fields=["app", "locale"], name="unique_app_locale")]

    def __str__(self):
        return f"{self.app} · {self.locale}"


def asset_upload_path(instance, filename):
    return f"apps/{instance.app.slug}/assets/{instance.platform}/{instance.locale}/{filename}"

class AppAsset(TimeStampedModel):
    KINDS = [("icon", "App icon"), ("screenshot", "Screenshot"), ("feature_graphic", "Feature graphic"), ("promo", "Promo graphic"), ("review_attachment", "Review attachment")]
    PLATFORMS = [("shared", "Shared"), ("android", "Android"), ("ios", "iOS")]
    app = models.ForeignKey(MobileApp, related_name="assets", on_delete=models.CASCADE)
    kind = models.CharField(max_length=30, choices=KINDS)
    platform = models.CharField(max_length=20, choices=PLATFORMS, default="shared")
    locale = models.CharField(max_length=20, default="en-US")
    device_type = models.CharField(max_length=80, blank=True)
    file = models.FileField(upload_to=asset_upload_path)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["platform", "locale", "kind", "sort_order"]

    def __str__(self):
        return f"{self.app} · {self.kind} · {self.locale}"

class Release(TimeStampedModel):
    STATUSES = [("draft", "Draft"), ("checking", "Checking"), ("building", "Building"), ("ready", "Ready"), ("submitted", "Submitted"), ("in_review", "In review"), ("approved", "Approved"), ("rejected", "Rejected"), ("released", "Released"), ("failed", "Failed")]
    app = models.ForeignKey(MobileApp, related_name="releases", on_delete=models.CASCADE)
    version_name = models.CharField(max_length=60)
    build_number = models.PositiveIntegerField()
    source_branch = models.CharField(max_length=120, default="main")
    source_commit = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=30, choices=STATUSES, default="draft")
    android_track = models.CharField(max_length=30, default="internal")
    android_rollout = models.DecimalField(max_digits=5, decimal_places=4, default=1)
    ios_release_type = models.CharField(max_length=30, default="manual")
    auto_submit = models.BooleanField(default=False)
    release_notes = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["app", "build_number"], name="unique_app_build_number")]

    def __str__(self):
        return f"{self.app} {self.version_name} ({self.build_number})"

    def get_absolute_url(self):
        return reverse("release_detail", args=[self.pk])

class BuildArtifact(TimeStampedModel):
    PLATFORMS = [("android", "Android"), ("ios", "iOS")]
    STATUSES = [("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")]
    release = models.ForeignKey(Release, related_name="builds", on_delete=models.CASCADE)
    platform = models.CharField(max_length=20, choices=PLATFORMS)
    status = models.CharField(max_length=20, choices=STATUSES, default="queued")
    agent = models.ForeignKey("BuildAgent", null=True, blank=True, related_name="builds", on_delete=models.SET_NULL)
    artifact = models.FileField(upload_to="builds/%Y/%m/", blank=True)
    artifact_name = models.CharField(max_length=255, blank=True)
    artifact_size = models.BigIntegerField(default=0)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    logs = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["release", "platform"], name="unique_release_platform_build")]

    def __str__(self):
        return f"{self.release} · {self.platform}"

class ReleaseCheck(TimeStampedModel):
    LEVELS = [("pass", "Pass"), ("warning", "Warning"), ("error", "Error")]
    release = models.ForeignKey(Release, related_name="checks", on_delete=models.CASCADE)
    platform = models.CharField(max_length=20, blank=True)
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=220)
    detail = models.TextField(blank=True)
    level = models.CharField(max_length=20, choices=LEVELS)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

class Job(TimeStampedModel):
    TYPES = [("sync_repository", "Sync repository"), ("run_checks", "Run checks"), ("build_android", "Build Android"), ("build_ios", "Build iOS"), ("upload_google", "Upload & submit Google"), ("upload_apple", "Upload & submit Apple"), ("sync_store_status", "Sync store status"), ("sync_google_reports", "Sync Google reports"), ("sync_apple_reports", "Sync Apple reports")]
    STATUSES = [("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("cancelled", "Cancelled")]
    type = models.CharField(max_length=40, choices=TYPES)
    app = models.ForeignKey(MobileApp, null=True, blank=True, related_name="jobs", on_delete=models.CASCADE)
    release = models.ForeignKey(Release, null=True, blank=True, related_name="jobs", on_delete=models.CASCADE)
    build = models.ForeignKey(BuildArtifact, null=True, blank=True, related_name="jobs", on_delete=models.SET_NULL)
    agent = models.ForeignKey("BuildAgent", null=True, blank=True, related_name="jobs", on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=STATUSES, default="queued")
    progress = models.PositiveSmallIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    logs = models.TextField(blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} #{self.pk}"

class BuildAgent(TimeStampedModel):
    PLATFORMS = [("macos", "macOS"), ("linux", "Linux"), ("windows", "Windows")]
    name = models.CharField(max_length=160, unique=True)
    platform = models.CharField(max_length=20, choices=PLATFORMS)
    token_hash = models.CharField(max_length=64, unique=True, blank=True)
    enabled = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    capabilities = models.JSONField(default=dict, blank=True)
    labels = models.JSONField(default=list, blank=True)
    current_job = models.ForeignKey(Job, null=True, blank=True, related_name="claimed_by", on_delete=models.SET_NULL)

    @property
    def online(self):
        return bool(self.last_seen_at and self.last_seen_at > timezone.now() - timedelta(minutes=5))

    @classmethod
    def issue_token(cls):
        token = secrets.token_urlsafe(36)
        return token, hashlib.sha256(token.encode()).hexdigest()

    def verify_token(self, token):
        return secrets.compare_digest(self.token_hash, hashlib.sha256(token.encode()).hexdigest())

class TechnicalIssue(TimeStampedModel):
    SEVERITIES = [("critical", "Critical"), ("high", "High"), ("medium", "Medium"), ("low", "Low")]
    STATUSES = [("open", "Open"), ("acknowledged", "Acknowledged"), ("resolved", "Resolved"), ("ignored", "Ignored")]
    STORES = [("google", "Google Play"), ("apple", "Apple"), ("github", "GitHub"), ("build", "Build")]
    app = models.ForeignKey(MobileApp, related_name="issues", on_delete=models.CASCADE)
    store = models.CharField(max_length=20, choices=STORES)
    external_id = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITIES, default="medium")
    status = models.CharField(max_length=20, choices=STATUSES, default="open")
    title = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    occurrences = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]

    def __str__(self):
        return self.title