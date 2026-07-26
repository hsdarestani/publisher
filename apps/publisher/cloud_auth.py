from __future__ import annotations

import hashlib
import os

import jwt
from jwt import PyJWKClient

from .models import BuildAgent


_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
_GITHUB_JWKS = PyJWKClient(f"{_GITHUB_OIDC_ISSUER}/.well-known/jwks")


def github_cloud_agent(request):
    """Authenticate the official A+ GitHub-hosted macOS workflow via OIDC.

    No persistent agent secret is required. The token is short-lived, signed by
    GitHub and restricted to the configured repository, main branch, audience,
    and the cloud macOS workflow's supported trigger events.
    """

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
    except Exception:
        return None

    if claims.get("repository") != allowed_repository:
        return None
    if claims.get("ref") != "refs/heads/main":
        return None
    if claims.get("event_name") not in {"schedule", "workflow_dispatch", "push"}:
        return None

    workflow_ref = claims.get("workflow_ref", "")
    if workflow_ref and ".github/workflows/cloud-macos.yml@" not in workflow_ref:
        return None

    token_hash = hashlib.sha256(
        f"github-oidc:{allowed_repository}:cloud-macos".encode()
    ).hexdigest()
    agent, _ = BuildAgent.objects.get_or_create(
        token_hash=token_hash,
        defaults={
            "name": "A+ Cloud Mac · GitHub Actions",
            "platform": "macos",
            "enabled": True,
            "labels": ["github-hosted", "ephemeral", "xcode", "cloud"],
            "capabilities": {"oidc": True, "ephemeral": True},
        },
    )

    changed = []
    if not agent.enabled:
        agent.enabled = True
        changed.append("enabled")
    if agent.platform != "macos":
        agent.platform = "macos"
        changed.append("platform")
    if changed:
        changed.append("updated_at")
        agent.save(update_fields=changed)
    return agent
