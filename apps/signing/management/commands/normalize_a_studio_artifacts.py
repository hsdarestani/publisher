from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.publisher.models import Job, MobileApp, Release


class Command(BaseCommand):
    help = "Restore A+ Studio native build state from successful build-agent jobs without retrying store uploads."

    def add_arguments(self, parser):
        parser.add_argument("--app-version", default="1.0.0")
        parser.add_argument("--build-number", type=int, default=1)

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug="a-studio").first()
        if not app:
            raise CommandError("A+ Studio is not registered in Publisher.")
        release = Release.objects.filter(
            app=app,
            version_name=options["app_version"],
            build_number=options["build_number"],
        ).first()
        if not release:
            raise CommandError("A+ Studio release was not found.")

        restored = []
        for platform, job_type in (("android", "build_android"), ("ios", "build_ios")):
            build = release.builds.filter(platform=platform).first()
            if not build:
                continue
            successful_job = (
                Job.objects.filter(
                    release=release,
                    build=build,
                    type=job_type,
                    status="succeeded",
                )
                .order_by("-finished_at", "-created_at")
                .first()
            )
            if not successful_job or not build.artifact:
                self.stdout.write(
                    self.style.WARNING(
                        f"{platform}=not_restored successful_job={'yes' if successful_job else 'no'} artifact={'yes' if build.artifact else 'no'}"
                    )
                )
                continue

            build.status = "succeeded"
            build.finished_at = successful_job.finished_at
            build.logs = successful_job.logs
            if successful_job.result:
                build.metadata = successful_job.result
                if successful_job.result.get("external_build_id"):
                    build.external_build_id = successful_job.result["external_build_id"]
            build.save(
                update_fields=[
                    "status",
                    "finished_at",
                    "logs",
                    "metadata",
                    "external_build_id",
                    "updated_at",
                ]
            )
            restored.append(platform)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{platform}=succeeded artifact={build.artifact.name} size={build.artifact_size} checksum={build.artifact_checksum}"
                )
            )

        builds = list(release.builds.all())
        if builds and all(build.status == "succeeded" for build in builds):
            release.status = "ready"
            release.save(update_fields=["status", "updated_at"])

        self.stdout.write(f"release_status={release.status}")
        self.stdout.write(f"restored={','.join(restored) if restored else 'none'}")
