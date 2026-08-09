from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from apps.publisher.models import Build, Job, MobileApp, Release
from apps.publisher.tasks import enqueue_job


TARGETS = (
    {
        "key": "solution",
        "repo_match": "aplussolution",
        "name_match": "A+ Solution",
        "source_commit": "1d49500db4b8a02b2a0f1ac01ea314eb82984e00",
    },
    {
        "key": "esthetic",
        "repo_match": "a_esthetic",
        "name_match": "A+ Esthetic",
        "source_commit": "7200135711da910cd742c55dac1fc9ca5f26a51d",
    },
)


class Command(BaseCommand):
    help = "Queue, diagnose and publish the Android launcher-icon update for A+ Solution and A+ Esthetic."

    def add_arguments(self, parser):
        parser.add_argument("--queue", action="store_true", help="Create/reuse releases and queue Android builds.")
        parser.add_argument("--publish", action="store_true", help="Queue Google Play upload once the Android build succeeds.")
        parser.add_argument("--diagnose", action="store_true", help="Print the latest Android build/upload errors and log tails.")
        parser.add_argument(
            "--target",
            action="append",
            choices=[item["key"] for item in TARGETS],
            help="Limit to one target. Can be repeated.",
        )

    def handle(self, *args, **options):
        if not options["queue"] and not options["publish"] and not options["diagnose"]:
            options["queue"] = True

        selected = set(options.get("target") or [item["key"] for item in TARGETS])
        failures = []

        for target in TARGETS:
            if target["key"] not in selected:
                continue
            try:
                app = self._find_app(target)
                release = self._release_for_target(app, target, create=options["queue"])
                if not release:
                    self.stdout.write(f"{target['key']}: release=missing")
                    continue

                if options["queue"]:
                    self._queue_build(app, release)

                if options["publish"]:
                    self._queue_publish(app, release)

                line = self._status_line(target["key"], app, release)
                self.stdout.write(line)

                if options["diagnose"]:
                    self._diagnose(target["key"], release)

                if not options["diagnose"] and (
                    "build_android=failed" in line or "upload_google=failed" in line
                ):
                    failures.append(line)
            except Exception as exc:
                failures.append(f"{target['key']}: {exc}")
                self.stderr.write(self.style.ERROR(f"FAILED:{target['key']}: {exc}"))

        if failures:
            raise CommandError("; ".join(failures))

    def _find_app(self, target):
        app = (
            MobileApp.objects.filter(repository_url__icontains=target["repo_match"])
            .order_by("-updated_at")
            .first()
        )
        if not app:
            app = (
                MobileApp.objects.filter(name__icontains=target["name_match"])
                .order_by("-updated_at")
                .first()
            )
        if not app:
            raise RuntimeError(f"Publisher app not found for {target['key']}")
        if not app.supports_android:
            raise RuntimeError(f"{app.name} does not support Android")
        if not app.google_account or not app.google_account.configured:
            raise RuntimeError(f"Google Play account is not configured for {app.name}")
        if not app.repository_url:
            raise RuntimeError(f"Repository URL is missing for {app.name}")
        return app

    def _release_for_target(self, app, target, *, create):
        release = (
            app.releases.filter(source_commit=target["source_commit"])
            .order_by("-created_at")
            .first()
        )
        if release or not create:
            return release

        latest = app.releases.order_by("-created_at").first()
        version_name = latest.version_name if latest else "1.0.0"
        max_build = app.releases.aggregate(value=Max("build_number"))["value"] or 0
        build_number = max_build + 1

        release = Release.objects.create(
            app=app,
            version_name=version_name,
            build_number=build_number,
            status="draft",
            source_branch=app.default_branch or "main",
            source_commit=target["source_commit"],
            android_track="production",
            android_rollout=Decimal("1.0000"),
            auto_submit=True,
            release_notes="Kleine technische Aktualisierung der App-Darstellung.",
        )
        Build.objects.create(release=release, platform="android")
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {app.name} {release.version_name} ({release.build_number}) from {target['source_commit'][:12]}"
            )
        )
        return release

    def _queue_build(self, app, release):
        build = release.builds.filter(platform="android").first()
        if not build:
            build = Build.objects.create(release=release, platform="android")

        active = Job.objects.filter(
            release=release,
            build=build,
            type="build_android",
            status__in=["queued", "running", "succeeded"],
        ).exists()
        if active:
            return

        if build.status in {"failed", "cancelled"}:
            build.status = "queued"
            build.logs = ""
            build.started_at = None
            build.finished_at = None
            build.save(
                update_fields=[
                    "status",
                    "logs",
                    "started_at",
                    "finished_at",
                    "updated_at",
                ]
            )

        enqueue_job(
            "build_android",
            app=app,
            release=release,
            build=build,
            agent=True,
            platform="linux",
        )
        release.status = "building"
        release.save(update_fields=["status", "updated_at"])

    def _queue_publish(self, app, release):
        build = release.builds.filter(platform="android").first()
        if not build or build.status != "succeeded":
            return

        active = Job.objects.filter(
            release=release,
            type="upload_google",
            status__in=["queued", "running", "succeeded"],
        ).exists()
        if active:
            return

        failed = Job.objects.filter(
            release=release,
            type="upload_google",
            status="failed",
        ).exists()
        if failed:
            return

        enqueue_job("upload_google", app=app, release=release, build=build)

    def _diagnose(self, key, release):
        build = release.builds.filter(platform="android").first()
        if build:
            self.stdout.write(f"--- {key} build metadata ---")
            self.stdout.write(f"status={build.status} commit={build.commit_sha or '-'}")
            if build.logs:
                self.stdout.write(build.logs[-16000:])

        for job_type in ("build_android", "upload_google"):
            job = (
                Job.objects.filter(release=release, type=job_type)
                .order_by("-created_at")
                .first()
            )
            if not job:
                continue
            self.stdout.write(f"--- {key} {job_type} job={job.pk} status={job.status} ---")
            if job.error:
                self.stdout.write(f"ERROR: {job.error}")
            if job.logs:
                self.stdout.write(job.logs[-16000:])

    def _status_line(self, key, app, release):
        build = release.builds.filter(platform="android").first()
        build_status = build.status if build else "missing"
        build_job = (
            Job.objects.filter(release=release, type="build_android")
            .order_by("-created_at")
            .first()
        )
        upload_job = (
            Job.objects.filter(release=release, type="upload_google")
            .order_by("-created_at")
            .first()
        )
        build_job_status = build_job.status if build_job else "missing"
        upload_status = upload_job.status if upload_job else "missing"
        return (
            f"{key}: app={app.slug} release={release.pk} version={release.version_name} "
            f"build={release.build_number} android_build={build_status} "
            f"build_android={build_job_status} upload_google={upload_status}"
        )
