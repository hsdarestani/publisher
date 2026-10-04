from __future__ import annotations

import json
import os
import secrets

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import MobileApp, Release, Build, Job, StoreAccount
from .tasks import enqueue_job
from .cloud_auth import github_release_automation
from apps.signing.services import ensure_ios_signing


def _authorized(request) -> bool:
    if github_release_automation(request):
        return True
    expected = os.getenv("PUBLISHER_AUTOMATION_TOKEN", "").strip()
    if not expected:
        return False
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    return bool(token) and secrets.compare_digest(token, expected)



def _bootstrap_known_app(identifier: str, body: dict) -> MobileApp | None:
    if identifier != "com.smarbiz.bedifferent":
        return None
    build_config = {
        "android_command": "bash mobile/scripts/build-android.sh",
        "android_artifact": "mobile/android/app/build/outputs/bundle/release/*.aab",
        "ios_command": "bash mobile/scripts/build-ios.sh",
        "ios_artifact": "mobile/ios/build/export/*.ipa",
        "env": {},
    }
    app, _ = MobileApp.objects.get_or_create(
        slug="be-different",
        defaults={
            "name": "BE DIFFERENT",
            "client_name": "BE DIFFERENT",
            "platform": "both",
            "framework": "react_native",
            "status": "active",
            "package_name": identifier,
            "bundle_id": identifier,
            "repository_url": "https://github.com/hsdarestani/aymantraining",
            "default_branch": "main",
            "privacy_policy_url": "https://bedifferent.smarbiz.sbs/legal/privacy",
            "support_url": "https://bedifferent.smarbiz.sbs/",
            "marketing_url": "https://bedifferent.smarbiz.sbs/",
            "category": "Health & Fitness",
            "requires_login": True,
            "build_config": build_config,
            "tech_stack": ["React Native", "Expo prebuild", "StoreKit 2", "Google Play Billing", "Firebase Cloud Messaging"],
        },
    )
    changed = False
    expected = {
        "name": "BE DIFFERENT",
        "platform": "both",
        "framework": "react_native",
        "status": "active",
        "package_name": identifier,
        "bundle_id": identifier,
        "repository_url": "https://github.com/hsdarestani/aymantraining",
        "default_branch": "main",
        "privacy_policy_url": "https://bedifferent.smarbiz.sbs/legal/privacy",
        "support_url": "https://bedifferent.smarbiz.sbs/",
        "marketing_url": "https://bedifferent.smarbiz.sbs/",
        "category": "Health & Fitness",
        "requires_login": True,
        "build_config": build_config,
    }
    for field, value in expected.items():
        if getattr(app, field) != value:
            setattr(app, field, value)
            changed = True

    if app.google_account_id is None:
        google = StoreAccount.objects.filter(provider="google", enabled=True).first()
        if google and google.configured:
            app.google_account = google
            changed = True
    if app.apple_account_id is None:
        apple = StoreAccount.objects.filter(provider="apple", enabled=True).first()
        if apple and apple.configured:
            app.apple_account = apple
            changed = True
    if changed:
        app.save()
    return app

@csrf_exempt
@require_POST
def automation_release(request):
    if not _authorized(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    identifier = str(body.get("app_identifier") or "").strip()
    version = str(body.get("version_name") or "").strip()
    try:
        build_number = int(body.get("build_number"))
    except Exception:
        build_number = 0

    if not identifier or not version or build_number < 1:
        return JsonResponse(
            {"ok": False, "error": "app_identifier, version_name and positive build_number are required"},
            status=422,
        )

    if identifier == "com.smarbiz.bedifferent":
        app = _bootstrap_known_app(identifier, body)
    else:
        app = (
            MobileApp.objects.filter(bundle_id=identifier).first()
            or MobileApp.objects.filter(package_name=identifier).first()
            or MobileApp.objects.filter(slug=identifier).first()
        )
    if not app:
        return JsonResponse({"ok": False, "error": "app_not_found"}, status=404)

    requested = body.get("platforms") or ["android", "ios"]
    platforms = [p for p in requested if p in {"android", "ios"}]
    platforms = [
        p for p in platforms
        if (p == "android" and app.supports_android) or (p == "ios" and app.supports_ios)
    ]
    if not platforms:
        return JsonResponse({"ok": False, "error": "no_supported_platforms"}, status=422)

    if "ios" in platforms and app.apple_account_id:
        try:
            ensure_ios_signing(app)
        except Exception as exc:
            return JsonResponse({
                "ok": False,
                "error": "ios_signing_provisioning_failed",
                "detail": str(exc),
            }, status=409)

    source_commit = str(body.get("source_commit") or "").strip()
    source_branch = str(body.get("source_branch") or app.default_branch or "main").strip()
    android_track = str(body.get("android_track") or "internal").strip()
    auto_submit = bool(body.get("auto_submit", False))
    release_notes = str(body.get("release_notes") or "").strip()

    queued = []
    skipped = []

    with transaction.atomic():
        release, created = Release.objects.get_or_create(
            app=app,
            version_name=version,
            build_number=build_number,
            defaults={
                "source_branch": source_branch,
                "source_commit": source_commit,
                "android_track": android_track,
                "auto_submit": auto_submit,
                "release_notes": release_notes,
            },
        )
        if not created:
            changed = False
            for field, value in {
                "source_branch": source_branch,
                "source_commit": source_commit,
                "android_track": android_track,
                "auto_submit": auto_submit,
                "release_notes": release_notes,
            }.items():
                if value != getattr(release, field):
                    setattr(release, field, value)
                    changed = True
            if changed:
                release.save()

        for platform in platforms:
            job_type = f"build_{platform}"
            build = release.builds.filter(platform=platform).first()
            if not build:
                build = Build.objects.create(release=release, platform=platform)

            active = Job.objects.filter(
                release=release,
                build=build,
                type=job_type,
                status__in=["queued", "running", "succeeded"],
            ).order_by("-created_at").first()
            if active:
                skipped.append({"platform": platform, "job_id": active.pk, "status": active.status})
                continue

            build.status = "queued"
            build.logs = ""
            build.save(update_fields=["status", "logs", "updated_at"])
            job = enqueue_job(
                job_type,
                app=app,
                release=release,
                build=build,
                agent=True,
                platform="linux" if platform == "android" else "macos",
            )
            queued.append({"platform": platform, "job_id": job.pk})

        if queued:
            release.status = "building"
            release.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "ok": True,
        "app": app.slug,
        "release_id": release.pk,
        "version_name": release.version_name,
        "build_number": release.build_number,
        "queued": queued,
        "skipped": skipped,
        "release_url": release.get_absolute_url(),
    })
