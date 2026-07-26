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
    checksum = models.CharField(max_length=64, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["platform", "locale", "kind", "sort_order"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.file and not self.checksum:
            try:
                h = hashlib.sha256()
                for chunk in self.file.chunks():
                    h.update(chunk)
                self.checksum = h.hexdigest()
                super().save(update_fields=["checksum"])
            except Exception:
                pass

class Release(TimeStampedModel):
    STATUSES = [("draft", "Draft"), ("checking", "Checking"), ("ready", "Ready"), ("building", "Building"), ("uploaded", "Uploaded"), ("in_review", "In review"), ("approved", "Approved"), ("released", "Released"), ("rejected", "Rejected"), ("failed", "Failed")]
    app = models.ForeignKey(MobileApp, related_name="releases", on_delete=models.CASCADE)
    version_name = models.CharField(max_length=40)
    build_number = models.PositiveIntegerField()
    status = models.CharField(max_length=30, choices=STATUSES, default="draft")
    source_branch = models.CharField(max_length=120, blank=True)
    source_commit = models.CharField(max_length=64, blank=True)
    android_track = models.CharField(max_length=40, default="internal")
    android_rollout = models.DecimalField(max_digits=5, decimal_places=4, default=1)
    ios_release_type = models.CharField(max_length=40, default="manual")
    auto_submit = models.BooleanField(default=False)
    release_notes = models.TextField(blank=True)
    readiness_snapshot = models.JSONField(default=dict, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["app", "version_name", "build_number"], name="unique_release_build")]

    def __str__(self):
        return f"{self.app.name} {self.version_name} ({self.build_number})"

    def get_absolute_url(self):
        return reverse("release_detail", args=[self.pk])

class BuildAgent(TimeStampedModel):
    PLATFORMS = [("linux", "Linux / Android"), ("macos", "macOS / iOS"), ("universal", "Universal")]
    name = models.CharField(max_length=120, unique=True)
    platform = models.CharField(max_length=20, choices=PLATFORMS)
    enabled = models.BooleanField(default=True)
    token_hash = models.CharField(max_length=64, unique=True)
    labels = models.JSONField(default=list, blank=True)
    capabilities = models.JSONField(default=dict, blank=True)
    hostname = models.CharField(max_length=180, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    current_job = models.ForeignKey("Job", null=True, blank=True, related_name="assigned_agents", on_delete=models.SET_NULL)

    class Meta:
        ordering = ["name"]

    @classmethod
    def create_with_token(cls, **kwargs):
        token = secrets.token_urlsafe(36)
        obj = cls.objects.create(token_hash=hashlib.sha256(token.encode()).hexdigest(), **kwargs)
        return obj, token

    def verify_token(self, token: str) -> bool:
        return secrets.compare_digest(self.token_hash, hashlib.sha256(token.encode()).hexdigest())

    @property
    def online(self):
        return bool(self.last_seen_at and self.last_seen_at >= timezone.now() - timedelta(minutes=5))

    def __str__(self):
        return self.name

class Build(TimeStampedModel):
    PLATFORMS = [("android", "Android"), ("ios", "iOS")]
    STATUSES = [("queued", "Queued"), ("claimed", "Claimed"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("cancelled", "Cancelled")]
    release = models.ForeignKey(Release, related_name="builds", on_delete=models.CASCADE)
    platform = models.CharField(max_length=20, choices=PLATFORMS)
    status = models.CharField(max_length=20, choices=STATUSES, default="queued")
    agent = models.ForeignKey(BuildAgent, null=True, blank=True, related_name="builds", on_delete=models.SET_NULL)
    commit_sha = models.CharField(max_length=64, blank=True)
    artifact = models.FileField(upload_to="builds/%Y/%m/", blank=True)
    artifact_size = models.BigIntegerField(default=0)
    artifact_checksum = models.CharField(max_length=64, blank=True)
    logs = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    external_build_id = models.CharField(max_length=160, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.release} · {self.platform}"

class Job(TimeStampedModel):
    TYPES = [
        ("build_android", "Build Android"), ("build_ios", "Build iOS"),
        ("upload_google", "Upload Google Play"), ("upload_apple", "Upload App Store"),
        ("submit_google", "Submit Google review"), ("submit_apple", "Submit Apple review"),
        ("sync_google_reports", "Sync Google reports"), ("sync_apple_reports", "Sync Apple reports"),
        ("sync_store_status", "Sync store status"), ("sync_repository", "Sync repository"),
    ]
    STATUSES = [("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("cancelled", "Cancelled")]
    app = models.ForeignKey(MobileApp, null=True, blank=True, related_name="jobs", on_delete=models.CASCADE)
    release = models.ForeignKey(Release, null=True, blank=True, related_name="jobs", on_delete=models.CASCADE)
    build = models.ForeignKey(Build, null=True, blank=True, related_name="jobs", on_delete=models.CASCADE)
    type = models.CharField(max_length=40, choices=TYPES)
    status = models.CharField(max_length=20, choices=STATUSES, default="queued")
    progress = models.PositiveSmallIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    logs = models.TextField(blank=True)
    error = models.TextField(blank=True)
    available_to_agents = models.BooleanField(default=False)
    required_platform = models.CharField(max_length=20, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def append_log(self, line: str):
        self.logs = (self.logs + "\n" + line).strip()[-200000:]
        self.save(update_fields=["logs", "updated_at"])

    def __str__(self):
        return f"{self.get_type_display()} · {self.get_status_display()}"

class Submission(TimeStampedModel):
    PLATFORMS = [("android", "Google Play"), ("ios", "App Store")]
    app = models.ForeignKey(MobileApp, related_name="submissions", on_delete=models.CASCADE)
    release = models.ForeignKey(Release, related_name="submissions", on_delete=models.CASCADE)
    platform = models.CharField(max_length=20, choices=PLATFORMS)
    state = models.CharField(max_length=60, default="not_submitted")
    external_id = models.CharField(max_length=160, blank=True)
    store_url = models.URLField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["release", "platform"], name="unique_release_submission")]

    def __str__(self):
        return f"{self.release} · {self.platform}"
