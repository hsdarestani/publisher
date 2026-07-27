from __future__ import annotations

import logging

import requests
from django.conf import settings


logger = logging.getLogger(__name__)

_WORKFLOWS = {
    "linux": "cloud-linux.yml",
    "macos": "cloud-macos.yml",
}


def wake_cloud_agent(platform: str) -> bool:
    """Dispatch the matching GitHub-hosted build agent without breaking the app.

    A fine-grained token is optional. When it is absent, scheduled workflow runs remain
    the fallback and Publisher continues operating normally.
    """

    workflow = _WORKFLOWS.get((platform or "").lower())
    token = getattr(settings, "PUBLISHER_GITHUB_TOKEN", "").strip()
    if not workflow or not token:
        logger.info(
            "Cloud agent dispatch skipped for %s: workflow or optional token missing.",
            platform,
        )
        return False

    repository = getattr(
        settings, "PUBLISHER_GITHUB_REPOSITORY", "hsdarestani/publisher"
    ).strip()
    ref = getattr(settings, "PUBLISHER_GITHUB_REF", "main").strip() or "main"
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches"

    try:
        response = requests.post(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "A-Plus-Publisher",
            },
            json={"ref": ref},
            timeout=10,
        )
        if response.status_code == 204:
            logger.info("Dispatched %s for queued %s work.", workflow, platform)
            return True
        logger.warning(
            "GitHub workflow dispatch failed for %s with HTTP %s: %s",
            workflow,
            response.status_code,
            response.text[:500],
        )
    except requests.RequestException as exc:
        logger.warning("GitHub workflow dispatch failed for %s: %s", workflow, exc)
    return False
