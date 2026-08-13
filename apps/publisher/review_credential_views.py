from __future__ import annotations

import json
import os

import jwt
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from jwt import PyJWKClient

from .models import MobileApp


_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
_GITHUB_JWKS = PyJWKClient(f"{_GITHUB_OIDC_ISSUER}/.well-known/jwks")
_ALLOWED_REPOSITORY = "hsdarestani/KAYIHAUSTECHNIK"
_ALLOWED_WORKFLOW = ".github/workflows/publisher-store-review-credentials.yml@"


def _authorized_kayi_workflow(request) -> bool:
    token = request.headers.get("X-GitHub-OIDC", "").strip()
    if not token:
        return False
    audience = os.getenv("GITHUB_OIDC_AUDIENCE", "https://publisher.smarbiz.sbs").rstrip("/")
    try:
        signing_key = _GITHUB_JWKS.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=_GITHUB_OIDC_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "repository", "ref", "workflow_ref"]},
        )
    except Exception:
        return False

    return bool(
        claims.get("repository") == _ALLOWED_REPOSITORY
        and claims.get("ref") == "refs/heads/main"
        and claims.get("event_name") in {"workflow_dispatch", "push"}
        and _ALLOWED_WORKFLOW in claims.get("workflow_ref", "")
    )


@csrf_exempt
@require_POST
def set_store_review_credentials(request):
    """Accept a one-time A+Bau review login only from the dedicated KAYI main workflow.

    The password is encrypted by MobileApp.set_review_password and is never echoed
    in the response. This bridges the isolated A+Bau production host to Publisher
    without committing or logging a reusable Store-review secret.
    """

    if not _authorized_kayi_workflow(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    bundle_id = str(payload.get("bundle_id") or "").strip()
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if bundle_id != "de.kayihaustechnik.app":
        return JsonResponse({"ok": False, "error": "invalid_bundle"}, status=400)
    if not username or not password or len(password) < 20:
        return JsonResponse({"ok": False, "error": "invalid_credentials"}, status=400)

    app = (
        MobileApp.objects.filter(bundle_id=bundle_id).first()
        or MobileApp.objects.filter(package_name=bundle_id).first()
    )
    if not app:
        return JsonResponse({"ok": False, "error": "app_not_registered"}, status=404)

    app.review_username = username[:120]
    app.set_review_password(password)
    app.save(update_fields=["review_username", "review_password_blob", "updated_at"])

    return JsonResponse({"ok": True, "app_id": app.pk, "review_username": app.review_username})
