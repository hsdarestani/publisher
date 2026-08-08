from __future__ import annotations

import json

from django.core.management import BaseCommand, CommandError, call_command
from django.utils import timezone

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import BuildAgent, Job, MobileApp, Release
from apps.signing.services import ensure_ios_signing


APP_SLUG = "a-studio"
APP_ID = "de.aplussolution.studio"
APPLE_BUNDLE_NAME = "APlus Studio"


class Command(BaseCommand):
    help = "Repair A+ Studio Apple bundle/signing and reset orphaned native build jobs before re-queueing release 1.0.0."

    def add_arguments(self, parser):
        parser.add_argument("--app-version", default="1.0.0")
        parser.add_argument("--build-number", type=int, default=1)
        parser.add_argument("--no-reset", action="store_true", help="Keep active build jobs instead of resetting them.")

    def handle(self, *args, **options):
        app = (
            MobileApp.objects.select_related("apple_account", "google_account")
            .filter(slug=APP_SLUG)
            .first()
        )
        if not app:
            raise CommandError("A+ Studio is not registered in Publisher.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+ Studio has no configured Apple Store account.")

        release = Release.objects.filter(
            app=app,
            version_name=options["app_version"],
            build_number=options["build_number"],
        ).first()
        if not release:
            raise CommandError("A+ Studio release does not exist in Publisher.")

        self._ensure_bundle_id(app)
        profile = ensure_ios_signing(app)
        self.stdout.write(
            self.style.SUCCESS(
                f"ios_signing=ready profile={profile.profile_name} uuid={profile.profile_uuid}"
            )
        )

        if not options["no_reset"]:
            self._reset_orphaned_build_jobs(release)

        # bootstrap_a_studio is idempotent. Once the valid Apple Bundle ID exists,
        # its normal signing probe resolves the existing resource instead of trying
        # to create the legacy invalid `A+ Studio` Bundle ID name.
        call_command(
            "bootstrap_a_studio",
            app_version=options["app_version"],
            build_number=options["build_number"],
            queue=True,
            publish=True,
        )

    def _ensure_bundle_id(self, app):
        client = AppleStoreClient(app.apple_account)
        data = client.request("GET", f"/bundleIds?filter[identifier]={APP_ID}&limit=10")
        for item in data.get("data", []):
            if item.get("attributes", {}).get("identifier") == APP_ID:
                self.stdout.write("apple_bundle_id=existing")
                return item

        body = {
            "data": {
                "type": "bundleIds",
                "attributes": {
                    "identifier": APP_ID,
                    "name": APPLE_BUNDLE_NAME,
                    "platform": "IOS",
                },
            }
        }
        item = client.request("POST", "/bundleIds", data=json.dumps(body))["data"]
        self.stdout.write(self.style.SUCCESS("apple_bundle_id=registered"))
        return item

    def _reset_orphaned_build_jobs(self, release):
        active_jobs = list(
            Job.objects.filter(
                release=release,
                type__in=["build_android", "build_ios"],
                status__in=["queued", "running"],
            ).select_related("build")
        )
        if not active_jobs:
            self.stdout.write("orphaned_build_jobs=none")
            return

        now = timezone.now()
        active_ids = [job.pk for job in active_jobs]
        BuildAgent.objects.filter(current_job_id__in=active_ids).update(current_job=None)

        for job in active_jobs:
            job.status = "cancelled"
            job.progress = 0
            job.finished_at = now
            job.error = "Reset by A+ Studio release repair after an overlapping cloud-agent wake left the job orphaned."
            job.save(update_fields=["status", "progress", "finished_at", "error", "updated_at"])

            if job.build and job.build.status != "succeeded":
                job.build.status = "queued"
                job.build.agent = None
                job.build.started_at = None
                job.build.finished_at = None
                job.build.logs = (job.build.logs + "\nReset after orphaned Publisher cloud-agent run.").strip()
                job.build.save(
                    update_fields=[
                        "status",
                        "agent",
                        "started_at",
                        "finished_at",
                        "logs",
                        "updated_at",
                    ]
                )

        self.stdout.write(self.style.WARNING(f"orphaned_build_jobs=reset count={len(active_jobs)}"))
