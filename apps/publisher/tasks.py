from __future__ import annotations
from datetime import timedelta
import traceback
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import Job, MobileApp, Release, Build, Submission
from .readiness import evaluate_release
from .review_contacts import apple_review_contact
from .store_compliance import (
    apple_age_rating_profile,
    apple_content_rights_declaration,
    apple_uses_non_exempt_encryption,
)


def enqueue_job(job_type, *, app=None, release=None, build=None, payload=None, agent=False, platform=""):
    job = Job.objects.create(
        type=job_type, app=app or (release.app if release else None), release=release,
        build=build, payload=payload or {}, available_to_agents=agent, required_platform=platform,
    )
    if not agent:
        run_job.delay(job.pk)
    return job

@shared_task(bind=True, autoretry_for=(), retry_backoff=True)
def run_job(self, job_id):
    job = Job.objects.select_related("app", "release", "build").get(pk=job_id)
    if job.status not in {"queued", "running"}: return
    job.status, job.started_at, job.progress = "running", timezone.now(), 5
    job.save(update_fields=["status", "started_at", "progress", "updated_at"])
    try:
        handler = globals().get(f"handle_{job.type}")
        if not handler: raise RuntimeError(f"No handler for job type: {job.type}")
        result = handler(job) or {}
        job.status, job.result, job.progress, job.finished_at = "succeeded", result, 100, timezone.now()
        job.append_log("Completed successfully.")
    except Exception as exc:
        job.status, job.error, job.finished_at = "failed", str(exc), timezone.now()
        job.logs = (job.logs + "\n" + traceback.format_exc())[-200000:]
    job.save(update_fields=["status", "result", "progress", "finished_at", "error", "logs", "updated_at"])


def handle_sync_repository(job):
    from apps.reports.services import sync_repository
    job.progress = 30; job.save(update_fields=["progress"])
    return sync_repository(job.app)


def handle_sync_google_reports(job):
    from apps.reports.services import sync_google_monthly, sync_google_issues
    month = job.payload.get("year_month") or timezone.now().strftime("%Y%m")
    monthly = sync_google_monthly(job.app, month)
    issues = sync_google_issues(job.app)
    return {"monthly": monthly, "issues": issues}


def handle_sync_apple_reports(job):
    from apps.reports.services import sync_apple_analytics
    return sync_apple_analytics(job.app)


def handle_sync_store_status(job):
    app = job.app
    result = {}
    if app.google_account and app.google_account.configured:
        from apps.integrations.google_play import GooglePlayClient
        result["google_reviews"] = len(GooglePlayClient(app.google_account).reviews(app.package_name, 10))
    if app.apple_account and app.apple_account.configured:
        from apps.integrations.apple_store import AppleStoreClient
        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        result["apple_app"] = record.get("attributes", {})
    app.last_synced_at = timezone.now(); app.save(update_fields=["last_synced_at", "updated_at"])
    return result


def handle_upload_google(job):
    from apps.integrations.google_play import GooglePlayClient
    release = job.release
    check = evaluate_release(release)
    if not release.app.google_account or not release.app.google_account.configured:
        raise RuntimeError("Google Play account is not configured.")
    build = job.build or release.builds.filter(platform="android", status="succeeded").first()
    if not build: raise RuntimeError("No successful Android build found.")
    client = GooglePlayClient(release.app.google_account)
    result = client.publish_release(release.app, release, build, release.app.localizations.all(), release.app.assets.all(), submit=True)
    Submission.objects.update_or_create(app=release.app, release=release, platform="android", defaults={"state": "in_review", "submitted_at": timezone.now(), "raw": result})
    release.status = "in_review"; release.readiness_snapshot = check; release.save(update_fields=["status", "readiness_snapshot", "updated_at"])
    return result


def handle_submit_google(job):
    return handle_upload_google(job)


def handle_submit_apple(job):
    from apps.integrations.apple_assets import sync_app_store_screenshots
    from apps.integrations.apple_compliance import (
        apply_app_store_compliance,
        ensure_build_encryption_declaration,
    )
    from apps.integrations.apple_store import AppleStoreClient

    release, app = job.release, job.release.app
    if not app.apple_account or not app.apple_account.configured:
        raise RuntimeError("Apple account is not configured.")
    build = job.build or release.builds.filter(platform="ios", status="succeeded").first()
    if not build or not build.external_build_id:
        raise RuntimeError("A processed App Store build ID is required. Run the macOS upload job first.")

    client = AppleStoreClient(app.apple_account)
    record = client.find_app(app.bundle_id)
    version = client.ensure_version(record["id"], release.version_name)

    # App-level declarations are cheap, deterministic API writes and are required
    # for review eligibility. Apply them before asynchronous media processing so
    # a slow screenshot never hides or delays compliance progress.
    app_compliance = apply_app_store_compliance(
        client,
        record["id"],
        content_rights=apple_content_rights_declaration(app),
        age_rating=apple_age_rating_profile(app),
    )

    encryption_answer = apple_uses_non_exempt_encryption(app)
    if encryption_answer is not None:
        ensure_build_encryption_declaration(
            client,
            build.external_build_id,
            encryption_answer,
        )

    for loc in app.localizations.all():
        client.set_localization(version["id"], loc)
    screenshot_result = sync_app_store_screenshots(
        client,
        version["id"],
        app.localizations.all(),
        app.assets.filter(kind="screenshot", platform="ios"),
    )

    client.attach_build(version["id"], build.external_build_id)
    contact = apple_review_contact(app)
    client.set_review_details(version["id"], app, contact=contact or None)
    result = client.submit_version(record["id"], version["id"])
    result["screenshots"] = screenshot_result
    result["app_compliance"] = app_compliance
    if encryption_answer is not None:
        result["uses_non_exempt_encryption"] = encryption_answer

    Submission.objects.update_or_create(
        app=app,
        release=release,
        platform="ios",
        defaults={
            "state": "in_review",
            "external_id": result["submission"]["id"],
            "submitted_at": timezone.now(),
            "raw": result,
        },
    )
    release.status = "in_review"
    release.readiness_snapshot = evaluate_release(release)
    release.save(update_fields=["status", "readiness_snapshot", "updated_at"])
    return result

@shared_task
def sync_store_statuses():
    for app in MobileApp.objects.filter(status="active"):
        enqueue_job("sync_store_status", app=app)

@shared_task
def sync_daily_reports():
    for app in MobileApp.objects.filter(status="active"):
        if app.google_account and app.google_account.configured: enqueue_job("sync_google_reports", app=app)
        if app.apple_account and app.apple_account.configured: enqueue_job("sync_apple_reports", app=app)
        if app.repository_url: enqueue_job("sync_repository", app=app)

@shared_task
def cleanup_old_jobs():
    cutoff = timezone.now() - timedelta(days=90)
    Job.objects.filter(created_at__lt=cutoff, status__in=["succeeded", "cancelled"]).delete()
