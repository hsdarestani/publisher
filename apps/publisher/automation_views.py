from __future__ import annotations

import json
import os
import secrets

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import MobileApp, Release, Build, Job
from .tasks import enqueue_job


def _authorized(request) -> bool:
    expected = os.getenv("PUBLISHER_AUTOMATION_TOKEN", "").strip()
    if not expected:
        return False
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    return bool(token) and secrets.compare_digest(token, expected)


@csrf_exempt
@require_POST
def automation_release(request):
    if not os.getenv("PUBLISHER_AUTOMATION_TOKEN", "").strip():
        return JsonResponse({"ok": False, "error": "automation_not_configured"}, status=503)
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
