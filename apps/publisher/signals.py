from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .github_actions import wake_cloud_agent
from .models import Job


@receiver(post_save, sender=Job)
def wake_cloud_agent_for_queued_job(sender, instance: Job, created: bool, update_fields=None, **kwargs):
    """Wake the matching ephemeral runner whenever agent work enters the queue."""

    if not instance.available_to_agents or instance.status != "queued":
        return
    if not created and update_fields is not None and "status" not in update_fields:
        return

    platform = instance.required_platform
    transaction.on_commit(lambda: wake_cloud_agent(platform))
