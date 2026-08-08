from __future__ import annotations

import hashlib

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .cloud_auth import github_cloud_agent
from .models import BuildAgent, Job


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


@csrf_exempt
@require_POST
def ios_signing_material(request, job_pk):
    """Return signing data only to the agent currently executing this iOS job.

    The endpoint is intentionally job-scoped. It never renders credentials in
    the Publisher UI and the Cloud Mac runner discards them after the build.
    """

    agent = _agent_from_request(request)
    job = get_object_or_404(
        Job.objects.select_related("app", "app__apple_account"),
        pk=job_pk,
    )
    if not agent or agent.current_job_id != job.pk or job.type != "build_ios":
        return JsonResponse({"error": "unauthorized"}, status=401)

    app = job.app
    try:
        distribution = app.apple_account.ios_distribution_signing
        profile = app.ios_provisioning_profile
    except Exception:
        return JsonResponse({"error": "ios_signing_not_configured"}, status=409)

    dist_data = distribution.get_credentials()
    profile_data = profile.get_credentials()
    required = {
        "private_key_pem": dist_data.get("private_key_pem", ""),
        "certificate_content_base64": dist_data.get("certificate_content_base64", ""),
        "profile_content_base64": profile_data.get("profile_content_base64", ""),
        "profile_name": profile.profile_name,
        "profile_uuid": profile.profile_uuid,
        "bundle_id": app.bundle_id,
    }
    if not all(required.values()):
        return JsonResponse({"error": "ios_signing_incomplete"}, status=409)
    return JsonResponse(required)
