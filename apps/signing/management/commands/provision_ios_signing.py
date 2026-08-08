from django.core.management.base import BaseCommand, CommandError

from apps.publisher.models import Build, Job, MobileApp, Release
from apps.signing.services import ensure_ios_signing


class Command(BaseCommand):
    help = "Provision Apple Distribution signing/profile for an app and optionally queue its iOS build."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--version", default="1.0.0")
        parser.add_argument("--build-number", type=int, default=1)
        parser.add_argument("--no-queue", action="store_true")

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=options["slug"]).select_related("apple_account").first()
        if not app:
            raise CommandError(f"App not found: {options['slug']}")
        if not app.apple_account_id or not app.apple_account.configured:
            raise CommandError("App has no configured Apple Store account.")

        profile = ensure_ios_signing(app)
        distribution = profile.distribution_credential
        self.stdout.write(self.style.SUCCESS("ios_signing_ready=yes"))
        self.stdout.write(f"apple_certificate_id={distribution.apple_certificate_id}")
        self.stdout.write(f"profile_id={profile.apple_profile_id}")
        self.stdout.write(f"profile_uuid={profile.profile_uuid}")
        self.stdout.write(f"profile_name={profile.profile_name}")

        if options["no_queue"]:
            return

        release = Release.objects.filter(
            app=app,
            version_name=options["version"],
            build_number=options["build_number"],
        ).first()
        if not release:
            raise CommandError("Requested release does not exist.")
        build, _ = Build.objects.get_or_create(release=release, platform="ios")

        if build.status == "succeeded":
            self.stdout.write("ios_build_queue=already_succeeded")
            return
        if Job.objects.filter(
            app=app,
            release=release,
            build=build,
            type="build_ios",
            status__in=["queued", "running", "succeeded"],
        ).exists():
            self.stdout.write("ios_build_queue=already_live")
            return

        build.status = "queued"
        build.logs = ""
        build.save(update_fields=["status", "logs", "updated_at"])
        release.status = "building"
        release.save(update_fields=["status", "updated_at"])
        Job.objects.create(
            type="build_ios",
            app=app,
            release=release,
            build=build,
            payload={"source": "publisher-managed-ios-signing"},
            available_to_agents=True,
            required_platform="macos",
        )
        self.stdout.write(self.style.SUCCESS("ios_build_queue=queued"))
