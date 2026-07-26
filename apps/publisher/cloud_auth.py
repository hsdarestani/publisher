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
_CLOUD_AGENT_NAME = "A+ Cloud Mac · GitHub Actions"


def github_cloud_agent(request):
    """Authenticate the official A+ GitHub-hosted macOS workflow via OIDC."""

    token = request.headers.get("X-GitHub-OIDC", "").strip()
    if not token:
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
    }:
        return None

    workflow_ref = claims.get("workflow_ref", "")
    if workflow_ref and ".github/workflows/cloud-macos.yml@" not in workflow_ref:
        return None

    token_hash = hashlib.sha256(
        f"github-oidc:{allowed_repository}:cloud-macos".encode()
    ).hexdigest()

    with transaction.atomic():
        agent = BuildAgent.objects.select_for_update().filter(token_hash=token_hash).first()
        if agent is None:
            agent = BuildAgent.objects.select_for_update().filter(name=_CLOUD_AGENT_NAME).first()
        if agent is None:
            return BuildAgent.objects.create(
                name=_CLOUD_AGENT_NAME,
                platform="macos",
                enabled=True,
                token_hash=token_hash,
                labels=["github-hosted", "ephemeral", "xcode", "cloud"],
                capabilities={"oidc": True, "ephemeral": True},
            )

        agent.name = _CLOUD_AGENT_NAME
        agent.platform = "macos"
        agent.enabled = True
        agent.token_hash = token_hash
        agent.labels = ["github-hosted", "ephemeral", "xcode", "cloud"]
        agent.capabilities = {"oidc": True, "ephemeral": True}
        agent.save(
            update_fields=[
                "name",
                "platform",
                "enabled",
                "token_hash",
                "labels",
                "capabilities",
                "updated_at",
            ]
        )
        return agent
