from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.publisher.models import Build, Job, MobileApp, Release, Submission
from apps.publisher.tasks import enqueue_job


TARGET_SOURCE_COMMIT = "9d8fce132af4bf6fab63e97381cec0771eca846d"


class Command(BaseCommand):
    help = "Drive the BE DIFFERENT 1.0.0 (2) release through native builds and store delivery."

    def add_arguments(self, parser):
        parser.add_argument("--source-commit", default="")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        app = MobileApp.objects.get(slug="be-different")
        release = Release.objects.get(app=app, version_name="1.0.0", build_number=2)

        changed = []
        source_commit = TARGET_SOURCE_COMMIT
        if release.source_commit != source_commit:
            release.source_commit = source_commit
            changed.append("source_commit")
        if not release.auto_submit:
            release.auto_submit = True
            changed.append("auto_submit")
        if release.android_track != "internal":
            release.android_track = "internal"
            changed.append("android_track")
        if changed:
            release.save(update_fields=[*changed, "updated_at"])

        queued = []
        state = {"release": {"id": release.pk, "status": release.status, "source_commit": release.source_commit, "auto_submit": release.auto_submit}}

        for platform, job_type, agent_platform in (
            ("android", "build_android", "linux"),
            ("ios", "build_ios", "macos"),
        ):
            build = release.builds.filter(platform=platform).first()
            if build is None:
                build = Build.objects.create(release=release, platform=platform)

            active = Job.objects.filter(
                release=release,
                build=build,
                type=job_type,
                status__in=["queued", "running"],
            ).order_by("-created_at").first()

            if build.status != "succeeded" and active is None:
                build.status = "queued"
                build.logs = ""
                build.agent = None
                build.started_at = None
                build.finished_at = None
                build.save(update_fields=["status", "logs", "agent", "started_at", "finished_at", "updated_at"])
                active = enqueue_job(
                    job_type,
                    app=app,
                    release=release,
                    build=build,
                    agent=True,
                    platform=agent_platform,
                )
                queued.append({"type": job_type, "job_id": active.pk})

            state[platform] = {
                "build_id": build.pk,
                "build_status": build.status,
                "external_build_id": build.external_build_id,
                "active_build_job": None if active is None else {"id": active.pk, "status": active.status},
            }

        android_build = release.builds.filter(platform="android", status="succeeded").first()
        android_submission = Submission.objects.filter(release=release, platform="android").first()
        android_submit_active = Job.objects.filter(
            release=release,
            type__in=["upload_google", "submit_google"],
            status__in=["queued", "running"],
        ).order_by("-created_at").first()
        if android_build and not android_submission and android_submit_active is None:
            job = enqueue_job("submit_google", app=app, release=release, build=android_build)
            queued.append({"type": "submit_google", "job_id": job.pk})
            android_submit_active = job

        ios_build = release.builds.filter(platform="ios", status="succeeded").first()
        ios_submission = Submission.objects.filter(release=release, platform="ios").first()
        upload_succeeded = Job.objects.filter(
            release=release,
            type="upload_apple",
            status="succeeded",
        ).order_by("-created_at").first()
        upload_active = Job.objects.filter(
            release=release,
            type="upload_apple",
            status__in=["queued", "running"],
        ).order_by("-created_at").first()

        if ios_build and not upload_succeeded and upload_active is None:
            job = enqueue_job(
                "upload_apple",
                app=app,
                release=release,
                build=ios_build,
                agent=True,
                platform="macos",
            )
            queued.append({"type": "upload_apple", "job_id": job.pk})
            upload_active = job

        apple_submit_active = Job.objects.filter(
            release=release,
            type="submit_apple",
            status__in=["queued", "running"],
        ).order_by("-created_at").first()
        if ios_build and ios_build.external_build_id and upload_succeeded and not ios_submission and apple_submit_active is None:
            job = enqueue_job("submit_apple", app=app, release=release, build=ios_build)
            queued.append({"type": "submit_apple", "job_id": job.pk})
            apple_submit_active = job

        android_submission = Submission.objects.filter(release=release, platform="android").first()
        ios_submission = Submission.objects.filter(release=release, platform="ios").first()
        state["store"] = {
            "android": None if android_submission is None else {
                "state": android_submission.state,
                "external_id": android_submission.external_id,
                "last_error": android_submission.last_error,
            },
            "ios": None if ios_submission is None else {
                "state": ios_submission.state,
                "external_id": ios_submission.external_id,
                "last_error": ios_submission.last_error,
            },
        }
        state["queued"] = queued
        state["jobs"] = [
            {
                "id": j.pk,
                "type": j.type,
                "status": j.status,
                "error": j.error[-500:] if j.error else "",
            }
            for j in Job.objects.filter(release=release).order_by("-created_at")[:16]
        ]
        state["finalized"] = bool(
            android_submission
            and android_submission.state in {"in_review", "ready_for_review", "approved", "live"}
            and ios_submission
            and ios_submission.state in {"in_review", "approved", "live"}
        )
        state["checked_at"] = timezone.now().isoformat()

        rendered = json.dumps(state, sort_keys=True)
        self.stdout.write(rendered)
        if state["finalized"]:
            self.stdout.write("BE_DIFFERENT_FINALIZED=true")
