from __future__ import annotations

import json

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .agent_completion import _agent_from_request
from .models import Job


BUILD_JOB_TYPES = {"build_android", "build_ios"}


def build_agent_payload(job):
    app, release = job.app, job.release
    payload = {
        "repository_url": app.repository_url,
        "repository_token": app.get_repository_token(),
        "branch": release.source_branch or app.default_branch,
        "commit": release.source_commit,
        "framework": app.framework,
        "version_name": release.version_name,
        "build_number": release.build_number,
        "package_name": app.package_name,
        "bundle_id": app.bundle_id,
        "build_config": app.build_config,
        "callback_base": "/apps/agent-api",
    }
    if job.type in {"build_ios", "upload_apple"} and app.apple_account and app.apple_account.configured:
        payload["apple"] = {
            "issuer_id": app.apple_account.apple_issuer_id,
            "key_id": app.apple_account.apple_key_id,
            "team_id": app.apple_account.apple_team_id,
            "private_key": app.apple_account.get_credentials().get("private_key", ""),
        }
        if job.type == "upload_apple" and job.build and job.build.artifact:
            payload["artifact_url"] = job.build.artifact.url
    return payload


@csrf_exempt
@require_POST
def agent_claim(request):
    """Claim queued agent work without conflating store work with native builds."""

    agent = _agent_from_request(request)
    if not agent:
        return JsonResponse({"error": "unauthorized"}, status=401)

    agent.last_seen_at = timezone.now()
    agent.hostname = request.headers.get("X-Agent-Hostname", "")
    agent.app_version = request.headers.get("X-Agent-Version", "")
    agent.save(update_fields=["last_seen_at", "hostname", "app_version", "updated_at"])

    allowed = [agent.platform]
    if agent.platform == "universal":
        allowed = ["linux", "macos"]

    with transaction.atomic():
        job = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(
                status="queued",
                available_to_agents=True,
                required_platform__in=allowed,
            )
            .first()
        )
        if not job:
            return JsonResponse({"job": None})

        job.status = "running"
        job.started_at = timezone.now()
        job.progress = 1
        job.save(update_fields=["status", "started_at", "progress", "updated_at"])

        # Only compilation/signing jobs own Build execution state. Store uploads
        # are a later delivery stage and must not turn a successful AAB/IPA back
        # into claimed/running.
        if job.build and job.type in BUILD_JOB_TYPES:
            job.build.status = "claimed"
            job.build.agent = agent
            job.build.started_at = timezone.now()
            job.build.save(update_fields=["status", "agent", "started_at", "updated_at"])

        agent.current_job = job
        agent.save(update_fields=["current_job", "updated_at"])

    return JsonResponse(
        {
            "job": {
                "id": job.pk,
                "type": job.type,
                "payload": build_agent_payload(job),
            }
        }
    )


@csrf_exempt
@require_POST
def agent_log(request, job_pk):
    """Store job progress while preserving successful native artifact state."""

    agent = _agent_from_request(request)
    job = get_object_or_404(Job, pk=job_pk)
    if not agent or agent.current_job_id != job.pk:
        return JsonResponse({"error": "unauthorized"}, status=401)

    data = json.loads(request.body or b"{}")
    job.append_log(data.get("line", ""))
    job.progress = min(99, int(data.get("progress", job.progress)))
    job.save(update_fields=["progress", "updated_at"])

    if job.build and job.type in BUILD_JOB_TYPES:
        job.build.logs = job.logs
        job.build.status = "running"
        job.build.save(update_fields=["logs", "status", "updated_at"])

    return JsonResponse({"ok": True})
