from __future__ import annotations

import logging

import redis
import requests
from django.conf import settings


logger = logging.getLogger(__name__)

# A dedicated BE DIFFERENT agent must not also start a generic A+ runner.
_WORKFLOWS = {
    ("linux", ""): "cloud-linux.yml",
    ("macos", ""): "cloud-macos.yml",
    ("linux", "be-different"): "be-different-cloud-linux.yml",
    ("macos", "be-different"): "be-different-cloud-macos.yml",
}

# Coalesce queue bursts across Django workers. Jobs that cannot be claimed
# are retried by the server-side queued-job watchdog, not a GitHub cron.
_DISPATCH_COOLDOWN_SECONDS = 45


def wake_cloud_agent(platform: str, *, app_slug: str = "") -> bool:
    """Wake only the runner lane that can claim the newly queued job."""
    platform = (platform or "").lower()
    app_slug = "be-different" if app_slug == "be-different" else ""
    workflow = _WORKFLOWS.get((platform, app_slug))
    token = getattr(settings, "PUBLISHER_GITHUB_TOKEN", "").strip()
    if not workflow or not token:
        logger.warning(
            "Cloud dispatch skipped: platform=%s app=%s; workflow or token unavailable.",
            platform, app_slug or "other",
        )
        return False

    # Redis SET NX ensures two jobs saved in the same transaction cause only
    # one workflow launch. If Redis is down, fail open rather than lose builds.
    redis_client = None
    redis_key = f"publisher:cloud-dispatch:{workflow}"
    try:
        redis_client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1,
        )
        if not redis_client.set(
            redis_key, "1", nx=True, ex=_DISPATCH_COOLDOWN_SECONDS,
        ):
            logger.info("Cloud runner %s was dispatched recently; coalescing.", workflow)
            return True
    except (redis.RedisError, ValueError, OSError) as exc:
        logger.warning("Cloud dispatch deduplication unavailable: %s", exc)
        redis_client = None

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
            "GitHub dispatch failed for %s with HTTP %s: %s",
            workflow, response.status_code, response.text[:500],
        )
    except requests.RequestException as exc:
        logger.warning("GitHub dispatch failed for %s: %s", workflow, exc)

    # A failed API call must not suppress the next attempt.
    if redis_client is not None:
        try:
            redis_client.delete(redis_key)
        except redis.RedisError:
            logger.warning("Could not clear dispatch cooldown for %s", workflow)
    return False
