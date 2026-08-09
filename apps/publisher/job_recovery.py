from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import Job


RECOVERABLE_INTERNAL_JOB_TYPES = {"submit_apple", "upload_google", "submit_google"}


def recover_stale_internal_jobs(*, app, release, job_types=None, stale_after_minutes=15):
    """Fail internal Celery jobs that cannot still have a live worker.

    This intentionally excludes agent-owned build/upload jobs. GitHub-hosted build
    agents have their own lifecycle and may legitimately run for a long time. The
    helper is for Publisher-internal Celery work which can be orphaned when the
    Publisher container is restarted during a deploy.
    """

    requested = set(job_types or RECOVERABLE_INTERNAL_JOB_TYPES)
    unsupported = requested - RECOVERABLE_INTERNAL_JOB_TYPES
    if unsupported:
        raise ValueError(
            "Unsupported stale-job recovery types: " + ", ".join(sorted(unsupported))
        )

    cutoff = timezone.now() - timedelta(minutes=stale_after_minutes)
    stale = Job.objects.filter(
        app=app,
        release=release,
        type__in=requested,
        status="running",
        available_to_agents=False,
        started_at__lt=cutoff,
    ).order_by("created_at")

    recovered = []
    for job in stale:
        job.status = "failed"
        job.finished_at = timezone.now()
        job.error = (
            "Recovered stale internal Publisher job after a worker restart; "
            "safe to retry idempotently."
        )
        job.append_log(job.error)
        job.save(
            update_fields=[
                "status",
                "finished_at",
                "error",
                "updated_at",
            ]
        )
        recovered.append(job.pk)
    return recovered
