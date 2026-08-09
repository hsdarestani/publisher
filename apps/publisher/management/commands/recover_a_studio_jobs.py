from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.publisher.job_recovery import recover_stale_internal_jobs
from apps.publisher.models import MobileApp, Release


class Command(BaseCommand):
    help = "Recover stale internal A+ Studio store jobs after a Publisher worker restart."

    def add_arguments(self, parser):
        parser.add_argument("--app-version", default="1.0.0")
        parser.add_argument("--build-number", type=int, default=1)
        parser.add_argument("--stale-after-minutes", type=int, default=15)

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
        if options["stale_after_minutes"] < 5:
            raise CommandError("--stale-after-minutes must be at least 5")

        recovered = recover_stale_internal_jobs(
            app=app,
            release=release,
            job_types={"submit_apple", "upload_google", "submit_google"},
            stale_after_minutes=options["stale_after_minutes"],
        )
        if recovered:
            self.stdout.write(
                self.style.SUCCESS(
                    "recovered_stale_jobs=" + ",".join(str(pk) for pk in recovered)
                )
            )
        else:
            self.stdout.write("recovered_stale_jobs=none")
