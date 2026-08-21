from __future__ import annotations

import json
import textwrap

from django.core.management.base import CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp, Release, Submission
from apps.signing.management.commands.bootstrap_a_bau import Command as BaseReleaseCommand


APP_ID = "de.aplussolution.workforce"
APP_REPO = "https://github.com/hsdarestani/aplussolution"


class Command(BaseReleaseCommand):
    help = "Build and publish the A+ Solution native-push release without replacing existing Store credentials."

    def add_arguments(self, parser):
        parser.add_argument("--version", default="1.0.2")
        parser.add_argument("--build-number", type=int, default=8)
        parser.add_argument("--source-commit", default="")
        parser.add_argument("--queue", action="store_true")
        parser.add_argument("--publish", action="store_true")

    def handle(self, *args, **options):
        app = (
            MobileApp.objects.filter(package_name=APP_ID).first()
            or MobileApp.objects.filter(bundle_id=APP_ID).first()
        )
        if not app:
            raise CommandError(f"Publisher app {APP_ID} not found.")
        if not app.google_account or not app.google_account.configured:
            raise CommandError("A+ Solution Google Play account is not configured.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+ Solution Apple account is not configured.")

        config = dict(app.build_config or {})
        env = dict(config.get("env") or {})
        env["REQUIRE_NATIVE_PUSH"] = "1"
        config.update(
            {
                "android_command": "bash frontend/scripts/build-publisher-android.sh",
                "android_artifact": "frontend/android/app/build/outputs/bundle/release/*.aab",
                "ios_command": "bash frontend/scripts/build-publisher-ios.sh",
                "ios_artifact": "frontend/ios/build/export/*.ipa",
                "env": env,
            }
        )
        app.repository_url = APP_REPO
        app.default_branch = "main"
        app.package_name = APP_ID
        app.bundle_id = APP_ID
        app.platform = "both"
        app.framework = "other"
        app.build_config = config
        app.save(
            update_fields=[
                "repository_url",
                "default_branch",
                "package_name",
                "bundle_id",
                "platform",
                "framework",
                "build_config",
                "updated_at",
            ]
        )

        source_commit = str(options.get("source_commit") or "").strip()
        release, _ = Release.objects.update_or_create(
            app=app,
            version_name=options["version"],
            build_number=options["build_number"],
            defaults={
                "source_branch": "main",
                "source_commit": source_commit,
                "android_track": "production",
                "android_rollout": 1,
                "ios_release_type": "manual",
                "auto_submit": True,
                "release_notes": (
                    "Native Push-Benachrichtigungen für Android und iOS, verbesserte Benachrichtigungen "
                    "und Akten-Schnellzugriff sowie Stabilitätsverbesserungen."
                ),
            },
        )
        self._recover_stale(app, release)
        self._prepare_signing(app)
        if options["queue"]:
            self._queue_builds(app, release)
        if options["publish"]:
            self._advance_publication(app, release)
        self._report_aplus(app, release)

    def _ensure_apple_bundle_id(self, app):
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
                    "name": "A Plus Solution",
                    "platform": "IOS",
                },
            }
        }
        item = client.request("POST", "/bundleIds", data=json.dumps(body))["data"]
        self.stdout.write("apple_bundle_id=registered")
        return item

    def _report_aplus(self, app, release):
        records = self._store_records(app)
        self.stdout.write("--- aplus-solution-release-status ---")
        self.stdout.write(f"app={app.slug} package={app.package_name}")
        self.stdout.write(f"release={release.version_name}({release.build_number}) status={release.status}")
        self.stdout.write(f"source_commit={release.source_commit or '-'}")
        self.stdout.write(f"review_credentials={'ready' if app.review_username and app.get_review_password() else 'missing'}")
        self.stdout.write(f"google_record={'ready' if records['google']['ready'] else 'blocked'}")
        self.stdout.write(textwrap.shorten(f"google_detail={records['google']['message']}", width=600, placeholder="..."))
        self.stdout.write(f"apple_record={'ready' if records['apple']['ready'] else 'blocked'}")
        self.stdout.write(textwrap.shorten(f"apple_detail={records['apple']['message']}", width=600, placeholder="..."))
        for build in release.builds.order_by("platform"):
            self.stdout.write(
                f"build_{build.platform}={build.status} artifact={'yes' if build.artifact else 'no'} "
                f"external_id={build.external_build_id or '-'}"
            )
        for job in release.jobs.order_by("created_at"):
            self.stdout.write(
                f"job={job.type}:{job.status} error={textwrap.shorten(job.error or '-', width=500, placeholder='...')}"
            )
        for submission in Submission.objects.filter(release=release).order_by("platform"):
            self.stdout.write(
                f"submission_{submission.platform}={submission.state} external_id={submission.external_id or '-'}"
            )
