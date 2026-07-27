from __future__ import annotations

import uuid

from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.publisher.models import MobileApp


class ComplianceProfile(TimeStampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("analyzing", "Analyzing"),
        ("generated", "Generated"),
        ("needs_review", "Needs review"),
        ("ready", "Ready"),
        ("partially_applied", "Partially applied"),
        ("applied", "Applied"),
        ("failed", "Failed"),
    ]
    ACCESS_CHOICES = [
        ("unrestricted", "All functionality is available without access"),
        ("login", "Login or membership is required"),
        ("restricted", "Some functionality is otherwise restricted"),
    ]
    ACCOUNT_DELETION_CHOICES = [
        ("unknown", "Not confirmed yet"),
        ("in_app", "Users can delete their account inside the app"),
        ("web", "Users can request deletion on a public web page"),
        ("support", "Users can request deletion through support"),
        ("unavailable", "Account deletion is not available yet"),
        ("not_applicable", "The app does not create user accounts"),
    ]
    PAYMENT_HANDLING_CHOICES = [
        ("unknown", "Not confirmed yet"),
        ("none", "The app does not process payments"),
        ("external", "Payments are handled by an external provider"),
        ("direct", "The app or backend directly handles payment data"),
    ]

    app = models.OneToOneField(MobileApp, related_name="compliance", on_delete=models.CASCADE)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    primary_locale = models.CharField(max_length=20, default="de-DE")
    support_email = models.EmailField(blank=True)
    purpose = models.TextField(blank=True)
    business_model = models.CharField(max_length=120, blank=True)

    has_ads = models.BooleanField(default=False)
    target_age_groups = models.JSONField(default=list, blank=True)
    app_access = models.CharField(max_length=30, choices=ACCESS_CHOICES, default="unrestricted")
    app_access_instructions = models.TextField(blank=True)

    account_deletion = models.CharField(
        max_length=30,
        choices=ACCOUNT_DELETION_CHOICES,
        default="unknown",
    )
    account_deletion_url = models.URLField(blank=True)
    payment_handling = models.CharField(
        max_length=30,
        choices=PAYMENT_HANDLING_CHOICES,
        default="unknown",
    )
    payment_details = models.TextField(blank=True)

    source_analysis = models.JSONField(default=dict, blank=True)
    data_practices = models.JSONField(default=dict, blank=True)
    content_rating_answers = models.JSONField(default=dict, blank=True)
    store_declarations = models.JSONField(default=dict, blank=True)
    generated_content = models.JSONField(default=dict, blank=True)
    console_autofill = models.JSONField(default=dict, blank=True)
    unresolved_questions = models.JSONField(default=list, blank=True)

    privacy_policy_text = models.TextField(blank=True)
    data_safety_csv = models.TextField(blank=True)
    data_safety_template = models.FileField(upload_to="compliance/data-safety-templates/", blank=True)

    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=0)
    ai_used = models.BooleanField(default=False)
    ai_model = models.CharField(max_length=100, blank=True)
    last_generated_at = models.DateTimeField(null=True, blank=True)
    last_applied_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    companion_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    companion_token_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["app__name"]

    def __str__(self):
        return f"{self.app.name} · Google Play compliance"

    def get_absolute_url(self):
        return reverse("compliance_detail", args=[self.app_id])

    @property
    def privacy_policy_url(self):
        return reverse("public_privacy_policy", args=[self.app.slug])

    @property
    def companion_token_valid(self):
        return bool(self.companion_token_expires_at and self.companion_token_expires_at > timezone.now())


class ComplianceRun(TimeStampedModel):
    ACTIONS = [
        ("analyze", "Analyze source"),
        ("generate", "Generate compliance pack"),
        ("apply", "Apply Google APIs"),
        ("companion", "Console companion"),
    ]
    STATUSES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]

    profile = models.ForeignKey(ComplianceProfile, related_name="runs", on_delete=models.CASCADE)
    action = models.CharField(max_length=30, choices=ACTIONS)
    status = models.CharField(max_length=20, choices=STATUSES, default="queued")
    progress = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    logs = models.TextField(blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def append_log(self, message: str):
        self.logs = (self.logs + "\n" + message).strip()[-100000:]
        self.save(update_fields=["logs", "updated_at"])
