from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings
from django.core import signing

from apps.integrations.base import IntegrationError


WORKFLOW_FILE = "google-play-cloud-operation.yml"
TOKEN_SALT = "a-plus-publisher-google-play-cloud"


@dataclass
class CloudDispatch:
    workflow: str
    repository: str
    ref: str
    run_id: int

    def as_dict(self):
        return {
            "workflow": self.workflow,
            "repository": self.repository,
            "ref": self.ref,
            "run_id": self.run_id,
        }


def make_cloud_token(run_id: int) -> str:
    return signing.dumps({"run_id": run_id, "scope": "google-play-cloud"}, salt=TOKEN_SALT, compress=True)


def verify_cloud_token(token: str, run_id: int, max_age=3600) -> dict:
    payload = signing.loads(token, salt=TOKEN_SALT, max_age=max_age)
    if payload.get("scope") != "google-play-cloud" or int(payload.get("run_id", 0)) != int(run_id):
        raise signing.BadSignature("Cloud operation token does not match this compliance run.")
    return payload


def dispatch_google_play_cloud(run_id: int) -> CloudDispatch:
    token = settings.PUBLISHER_GITHUB_TOKEN.strip()
    repository = settings.PUBLISHER_GITHUB_REPOSITORY.strip()
    ref = settings.PUBLISHER_GITHUB_REF.strip() or "main"
    if not token:
        raise IntegrationError("PUBLISHER_GITHUB_TOKEN is missing; cloud Google Play fallback cannot be dispatched.")
    if not repository or "/" not in repository:
        raise IntegrationError("PUBLISHER_GITHUB_REPOSITORY is invalid.")

    callback_token = make_cloud_token(run_id)
    response = requests.post(
        f"https://api.github.com/repos/{repository}/actions/workflows/{WORKFLOW_FILE}/dispatches",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "ref": ref,
            "inputs": {
                "run_id": str(run_id),
                "publisher_url": settings.PUBLIC_URL.rstrip("/"),
                "callback_token": callback_token,
            },
        },
        timeout=30,
    )
    if response.status_code != 204:
        raise IntegrationError(
            f"GitHub cloud fallback dispatch failed: HTTP {response.status_code} {response.text[:500]}"
        )
    return CloudDispatch(WORKFLOW_FILE, repository, ref, run_id)
