from __future__ import annotations

from apps.publisher.models import Build, Job
from apps.signing.management.commands.bootstrap_smarbiz import Command as SmarbizCommand

SOURCE_COMMIT = "1177bbf9708501cd6df43f006c52f31dbe98d050"


class Command(SmarbizCommand):
    help = "Build the final Smarbiz 1.0.0 store artifacts from the pinned reviewed BrandFlowAI source commit."

    def _queue_one(self, app, release, platform):
        build, _ = Build.objects.get_or_create(release=release, platform=platform)
        if build.status == "succeeded":
            self.stdout.write(f"{platform}_build=already_succeeded")
            return
        job_type = "build_android" if platform == "android" else "build_ios"
        required = "linux" if platform == "android" else "macos"
        if Job.objects.filter(
            app=app,
            release=release,
            build=build,
            type=job_type,
            status__in=["queued", "running"],
        ).exists():
            self.stdout.write(f"{platform}_build=already_queued")
            return
        build.status = "queued"
        build.logs = ""
        build.save(update_fields=["status", "logs", "updated_at"])
        release.status = "building"
        release.save(update_fields=["status", "updated_at"])
        Job.objects.create(
            type=job_type,
            app=app,
            release=release,
            build=build,
            payload={
                "source": "smarbiz-final-store-build",
                "commit": SOURCE_COMMIT,
            },
            available_to_agents=True,
            required_platform=required,
        )
        self.stdout.write(self.style.SUCCESS(f"{platform}_build=queued commit={SOURCE_COMMIT}"))
