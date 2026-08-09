from __future__ import annotations

import hashlib
import logging
import os

import jwt
from django.db import transaction
from jwt import PyJWKClient

from .models import BuildAgent


logger = logging.getLogger(__name__)
_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
_GITHUB_JWKS = PyJWKClient(f"{_GITHUB_OIDC_ISSUER}/.well-known/jwks")

_AGENT_CONFIG = {
    "macos": {
        "name": "A+ Cloud Mac · GitHub Actions",
        "workflows": [".github/workflows/cloud-macos.yml@"],
        "labels": ["github-hosted", "ephemeral", "xcode", "cloud"],
        "capabilities": {"oidc": True, "ephemeral": True, "xcode": True},
    },
    "linux": {
        "name": "A+ Cloud Linux · GitHub Actions",
        "workflows": [
            ".github/workflows/cloud-linux.yml@",
            ".github/workflows/publish-launcher-fixes-via-cloud.yml@",
        ],
        "labels": ["github-hosted", "ephemeral", "flutter", "android", "cloud"],
        "capabilities": {"oidc": True, "ephemeral": True, "android": True},
    },
}


def _recover_interrupted_job(agent, request) -> None:
    """Requeue work left behind when an ephemeral GitHub runner terminated."""

    if not request.path.endswith("/agent-api/claim/") or not agent.current_job_id:
        return

    job = agent.current_job
    if job.status != "running":
        agent.current_job = None
        return

    job.logs = (
        job.logs
        + "\nPrevious ephemeral cloud runner stopped before completion; job was recovered automatically."
    ).strip()[-200000:]
    job.status = "queued"
    job.progress = 0
    job.started_at = None
    job.finished_at = None
    job.error = ""
    job.save(
        update_fields=[
            "logs",
            "status",
            "progress",
            "started_at",
            "finished_at",
            "error",
            "updated_at",
        ]
    )

    if job.build_id:
        build = job.build
        build.status = "queued"
        build.agent = None
        build.started_at = None
        build.finished_at = None
        build.logs = job.logs
        build.save(
            update_fields=[
                "status",
                "agent",
                "started_at",
                "finished_at",
                "logs",
                "updated_at",
            ]
        )

    agent.current_job = None


def github_cloud_agent(request):
    """Authenticate official A+ GitHub-hosted build workflows via OIDC."""

    token = request.headers.get("X-GitHub-OIDC", "").strip()
    platform = request.headers.get("X-Agent-Platform", "macos").strip().lower()
    config = _AGENT_CONFIG.get(platform)
    if not token or not config:
        return None

    audience = os.getenv("GITHUB_OIDC_AUDIENCE", "https://publisher.smarbiz.sbs").rstrip("/")
    allowed_repository = os.getenv("GITHUB_OIDC_REPOSITORY", "hsdarestani/publisher")

    try:
        signing_key = _GITHUB_JWKS.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=_GITHUB_OIDC_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "repository", "ref"]},
        )
    except Exception as exc:
        logger.warning("Rejected GitHub OIDC token: %s", exc)
        return None

    if claims.get("repository") != allowed_repository:
        return None
    if claims.get("ref") != "refs/heads/main":
        return None
    if claims.get("event_name") not in {
        "schedule",
        "workflow_dispatch",
        "workflow_run",
        "push",
    }:
        return None

    workflow_ref = claims.get("workflow_ref", "")
    allowed_workflows = config.get("workflows", [])
    if workflow_ref and allowed_workflows and not any(
        workflow in workflow_ref for workflow in allowed_workflows
    ):
        return None

    token_hash = hashlib.sha256(
        f"github-oidc:{allowed_repository}:cloud-{platform}".encode()
    ).hexdigest()

    with transaction.atomic():
        agent = BuildAgent.objects.select_for_update().filter(token_hash=token_hash).first()
        if agent is None:
            agent = BuildAgent.objects.select_for_update().filter(name=config["name"]).first()
        if agent is None:
            return BuildAgent.objects.create(
                name=config["name"],
                platform=platform,
                enabled=True,
                token_hash=token_hash,
                labels=config["labels"],
                capabilities=config["capabilities"],
            )

        _recover_interrupted_job(agent, request)
        agent.name = config["name"]
        agent.platform = platform
        agent.enabled = True
        agent.token_hash = token_hash
        agent.labels = config["labels"]
        agent.capabilities = config["capabilities"]
        agent.save(
            update_fields=[
                "name",
                "platform",
                "enabled",
                "token_hash",
                "labels",
                "capabilities",
                "current_job",
                "updated_at",
            ]
        )
        return agent
