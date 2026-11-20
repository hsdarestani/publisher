"""Narrow, OIDC-authenticated Vice Codes store handoff.

No public App Store submission, no Google production track, no credential
exposure. Read-only preflight uses the existing official store connectors.
"""
import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .cloud_auth import github_vice_codes_store_automation
from .models import Job, MobileApp, Release, Submission
from .tasks import enqueue_job


def _compact_job(job):
    return {
        "id": job.pk, "type": job.type, "status": job.status,
        "error": (job.error or "")[:1200],
    }


@csrf_exempt
@require_POST
def vice_codes_store(request):
    if not github_vice_codes_store_automation(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(body, dict) or body.get("app_identifier") != "de.smarbiz.vicecodes":
        return JsonResponse({"ok": False, "error": "invalid_app"}, status=403)

    app = MobileApp.objects.select_related("apple_account", "google_account").filter(slug="vice-codes").first()
    release = Release.objects.filter(pk=40, app=app, version_name="1.0.0", build_number=2).first() if app else None
    if not release:
        return JsonResponse({"ok": False, "error": "release_40_not_found"}, status=404)
    if release.android_track != "internal" or release.auto_submit:
        return JsonResponse({"ok": False, "error": "store_safety_gate", "reason": "Only internal testing with auto_submit off is supported."}, status=409)

    mode = body.get("mode", "preflight")
    if mode not in {"preflight", "upload_test", "status"}:
        return JsonResponse({"ok": False, "error": "unsupported_mode"}, status=400)
    builds = {b.platform: b for b in release.builds.all()}
    check = {
        p: bool(b and b.status == "succeeded" and b.artifact)
        for p, b in ((p, builds.get(p)) for p in ("ios", "android"))
    }
    shots = {
        "ios": app.assets.filter(kind="screenshot", platform="ios").count(),
        "android": app.assets.filter(kind="screenshot", platform="android").count(),
    }
    statuses = {
        "ios": {"linked": bool(app.apple_account and app.apple_account.configured), "build_ready": check["ios"]},
        "android": {"linked": bool(app.google_account and app.google_account.configured), "build_ready": check["android"]},
    }
    preflight = {}
    if mode != "status":
        if statuses["ios"]["linked"]:
            from apps.integrations.apple_store import AppleStoreClient
            try:
                found = AppleStoreClient(app.apple_account).find_app(app.bundle_id)
                preflight["ios"] = {"ok": True, "record_id": str(found["id"]), "bundle_id": app.bundle_id}
            except Exception as exc:
                preflight["ios"] = {"ok": False, "error": str(exc)[:1600]}
        else:
            preflight["ios"] = {"ok": False, "error": "Apple account is not linked to this app."}
        if statuses["android"]["linked"]:
            from apps.integrations.google_play import GooglePlayClient
            try:
                result = GooglePlayClient(app.google_account).test(app.package_name)
                preflight["android"] = {"ok": result.ok, "message": str(result.message)[:1800]}
            except Exception as exc:
                preflight["android"] = {"ok": False, "error": str(exc)[:1800]}
        else:
            preflight["android"] = {"ok": False, "error": "Google account is not linked to this app."}

    queued = []
    skipped = []
    if mode == "upload_test":
        for platform in ("ios", "android"):
            if not check[platform] or not preflight.get(platform, {}).get("ok"):
                skipped.append({"platform": platform, "reason": "Build or official store preflight failed."})
                continue
            job_type = "upload_apple" if platform == "ios" else "upload_google"
            with transaction.atomic():
                active = Job.objects.select_for_update().filter(
                    release=release, type=job_type, status__in=("queued", "running", "succeeded")
                ).order_by("-created_at").first()
                if active:
                    skipped.append({"platform": platform, "existing": _compact_job(active)})
                    continue
                if platform == "ios":
                    job = enqueue_job("upload_apple", app=app, release=release,
                        build=builds[platform], agent=True, platform="macos")
                else:
                    # Google uploader publishes ONLY to release.android_track ('internal').
                    job = enqueue_job("upload_google", app=app, release=release, build=builds[platform])
                queued.append({"platform": platform, "job": _compact_job(job)})

    prior = [
        _compact_job(job)
        for job in Job.objects.filter(release=release, type__in=("upload_apple", "upload_google")).order_by("-created_at")[:12]
    ]
    submissions = [
        {"platform": sub.platform, "state": sub.state,
         "external_id": sub.external_id, "last_error": (sub.last_error or "")[:500]}
        for sub in Submission.objects.filter(release=release).order_by("platform")
    ]
    return JsonResponse({
        "ok": True,
        "mode": mode,
        "app": app.slug,
        "release_id": release.pk,
        "privacy_policy_url": app.privacy_policy_url,
        "support_url": app.support_url,
        "screenshots_in_publisher": shots,
        "platforms": statuses,
        "preflight": preflight,
        "queued": queued,
        "skipped": skipped,
        "prior_jobs": prior,
        "submissions": submissions,
        "apple_processed_build_id": (builds["ios"].external_build_id if builds.get("ios") else ""),
        "android_track": release.android_track,
        "public_submission_queued": False,
    })
