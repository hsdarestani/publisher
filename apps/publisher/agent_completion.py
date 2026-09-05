from __future__ import annotations

import hashlib
import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .cloud_auth import github_cloud_agent
from .models import BuildAgent, Job
from .tasks import enqueue_job


def _agent_from_request(request):
    token = request.headers.get("X-Agent-Token", "")
    if token:
        agent = BuildAgent.objects.filter(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            enabled=True,
        ).first()
        if agent:
            return agent
    return github_cloud_agent(request)


def _save_build_artifact(build, artifact):
    build.artifact.save(artifact.name, artifact, save=False)
    build.artifact_size = artifact.size
    digest = hashlib.sha256()
    for chunk in artifact.chunks():
        digest.update(chunk)
    build.artifact_checksum = digest.hexdigest()


def _refresh_release_state(job, status):
    release = job.release
    if not release:
        return

    builds = list(release.builds.all())
    if job.type in {"build_android", "build_ios"}:
        if builds and all(build.status == "succeeded" for build in builds):
            release.status = "ready"
        elif any(build.status == "failed" for build in builds):
            release.status = "failed"
        else:
            release.status = "building"
    elif job.type == "upload_apple":
        # Store delivery is independent from native compilation. A failed upload
        # must never downgrade a valid signed IPA; a successful upload means the
        # binary is now available in App Store Connect.
        if status == "succeeded":
            release.status = "uploaded"
        elif builds and all(build.status == "succeeded" for build in builds):
            release.status = "ready"
    release.save(update_fields=["status", "updated_at"])


def _restore_native_ios_state(job, build):
    """Repair legacy claim/log mutations for an already-successful signed IPA."""

    if not build or not build.artifact:
        return False
    succeeded = Job.objects.filter(
        release=job.release,
        build=build,
        type="build_ios",
        status="succeeded",
    ).exists()
    if succeeded and build.status != "succeeded":
        build.status = "succeeded"
        return True
    return False


@csrf_exempt
@require_POST
def agent_complete(request, job_pk):
    """Complete an agent job without conflating native builds and store delivery."""

    agent = _agent_from_request(request)
    job = get_object_or_404(
        Job.objects.select_related(
            "build",
            "release",
            "app",
            "app__apple_account",
            "app__google_account",
        ),
        pk=job_pk,
    )
    if not agent or agent.current_job_id != job.pk:
        return JsonResponse({"error": "unauthorized"}, status=401)

    status = request.POST.get("status", "failed")
    succeeded = status == "succeeded"
    artifact = request.FILES.get("artifact")
    metadata = json.loads(request.POST.get("metadata", "{}") or "{}")
    error = request.POST.get("error", "")
    build = job.build

    if build and job.type in {"build_android", "build_ios"}:
        if artifact:
            _save_build_artifact(build, artifact)
        build.external_build_id = metadata.get(
            "external_build_id",
            build.external_build_id,
        )
        build.metadata = metadata
        build.status = "succeeded" if succeeded else "failed"
        build.finished_at = timezone.now()
        build.logs = job.logs + ("\n" + error if error else "")
        build.save()
    elif build and job.type == "upload_apple":
        # Older claim/log handlers briefly changed a successful IPA to
        # claimed/running. Restore that native state from the successful iOS
        # build job before recording the independent App Store upload result.
        update_fields = []
        if _restore_native_ios_state(job, build):
            update_fields.append("status")

        if succeeded:
            current_metadata = dict(build.metadata or {})
            current_metadata["apple_upload"] = metadata
            build.metadata = current_metadata
            build.external_build_id = metadata.get(
                "external_build_id",
                build.external_build_id,
            )
            update_fields.extend(["metadata", "external_build_id"])

        if update_fields:
            update_fields.append("updated_at")
            build.save(update_fields=list(dict.fromkeys(update_fields)))

    job.status = "succeeded" if succeeded else "failed"
    job.progress = 100 if succeeded else job.progress
    job.finished_at = timezone.now()
    job.error = error
    job.result = metadata
    job.save()

    agent.current_job = None
    agent.last_seen_at = timezone.now()
    agent.save(update_fields=["current_job", "last_seen_at", "updated_at"])

    # Auto-submit releases should move both native platforms forward as soon as
    # their signed artifacts are complete. Android submission runs on Celery;
    # iOS first needs the cloud Mac upload and then queues App Store submission.
    if (
        succeeded
        and job.type == "build_android"
        and build
        and job.release
        and job.release.auto_submit
        and job.app.google_account
        and job.app.google_account.configured
    ):
        exists = Job.objects.filter(
            release=job.release,
            type="submit_google",
            status__in=["queued", "running", "succeeded"],
        ).exists()
        if not exists:
            next_job = enqueue_job(
                "submit_google",
                app=job.app,
                release=job.release,
                build=build,
            )
            next_job.append_log(
                "Automatically queued after the cloud Android build because auto_submit is enabled."
            )

    if (
        succeeded
        and job.type == "build_ios"
        and build
        and job.release
        and job.release.auto_submit
        and job.app.apple_account
        and job.app.apple_account.configured
    ):
        exists = Job.objects.filter(
            build=build,
            type="upload_apple",
            status__in=["queued", "running", "succeeded"],
        ).exists()
        if not exists:
            next_job = enqueue_job(
                "upload_apple",
                app=job.app,
                release=job.release,
                build=build,
                agent=True,
                platform="macos",
            )
            next_job.append_log(
                "Automatically queued after the cloud iOS build because auto_submit is enabled."
            )

    if succeeded and job.type == "upload_apple" and job.release and job.release.auto_submit:
        exists = Job.objects.filter(
            release=job.release,
            type="submit_apple",
            status__in=["queued", "running", "succeeded"],
        ).exists()
        if not exists:
            enqueue_job(
                "submit_apple",
                app=job.app,
                release=job.release,
                build=build,
            )

    _refresh_release_state(job, status)
    return JsonResponse({"ok": True})
