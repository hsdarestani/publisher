from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.apple_store import AppleStoreClient
from apps.signing.services import ensure_android_signing, ensure_ios_signing

from apps.compliance.models import ComplianceProfile
from apps.compliance.services import _console_autofill
from apps.publisher.models import Build, Job, MobileApp, AppLocalization, Release, StoreAccount


APP_ID = "sbs.smarbiz.schichtpro"
APP_REPO = "https://github.com/hsdarestani/wiw"
PUBLIC_URL = "https://schichtpro.smarbiz.sbs"


class Command(BaseCommand):
    help = "Register SchichtPro in Publisher and optionally queue its native store builds."

    def add_arguments(self, parser):
        parser.add_argument("--app-version", default="1.0.0")
        parser.add_argument("--build-number", type=int, default=1)
        parser.add_argument("--queue", action="store_true")

    def handle(self, *args, **options):
        if options["build_number"] < 1:
            raise CommandError("--build-number must be >= 1")
        with transaction.atomic():
            app = self._upsert_app()
            self._upsert_localizations(app)
            self._upsert_compliance(app)
            release = self._upsert_release(app, options["app_version"], options["build_number"])
        if options["queue"]:
            self._prepare_signing(app)
            self._queue_builds(app, release)
        self._report(app, release)

    @staticmethod
    def _account(provider):
        return next(
            (a for a in StoreAccount.objects.filter(provider=provider, enabled=True).order_by("created_at") if a.configured),
            None,
        )

    def _upsert_app(self):
        app, created = MobileApp.objects.update_or_create(
            slug="schichtpro",
            defaults={
                "name": "SchichtPro",
                "client_name": "Smarbiz",
                "platform": "both",
                "framework": "react_native",
                "status": "active",
                "package_name": APP_ID,
                "bundle_id": APP_ID,
                "repository_url": APP_REPO,
                "default_branch": "main",
                "privacy_policy_url": f"{PUBLIC_URL}/privacy",
                "support_url": f"{PUBLIC_URL}/support",
                "marketing_url": PUBLIC_URL,
                "category": "Business",
                "content_rating": "4+ / Everyone",
                "requires_login": True,
                "review_notes": (
                    "SchichtPro is a workforce scheduling and time-clock app. Use a Publisher-managed review account. "
                    "Core flow: Schedule, OpenShifts, Time Clock, Requests, Inbox, Timesheets and Team. "
                    "Location is requested only when clocking in to validate the configured workplace."
                ),
                "google_account": self._account("google"),
                "apple_account": self._account("apple"),
                "build_config": {
                    "android_command": "bash apps/mobile/scripts/build-android.sh",
                    "android_artifact": "apps/mobile/artifacts/schichtpro-release.aab",
                    "ios_command": "bash apps/mobile/scripts/build-ios.sh",
                    "ios_artifact": "apps/mobile/artifacts/schichtpro.ipa",
                    "env": {"EXPO_PUBLIC_API_URL": PUBLIC_URL, "IOS_TEAM_ID": (self._account("apple").apple_team_id if self._account("apple") else "")},
                },
                "tech_stack": ["Expo 53", "React Native", "Next.js", "PostgreSQL", "Android", "iOS"],
            },
        )
        self.stdout.write(f"publisher_app={'created' if created else 'updated'} id={app.pk}")
        return app

    @staticmethod
    def _upsert_localizations(app):
        entries = {
            "de-DE": {
                "title": "SchichtPro", "subtitle": "Dienstplan & Zeiterfassung",
                "short_description": "Schichten planen, Zeiten erfassen und Teams koordinieren.",
                "full_description": "SchichtPro bringt Dienstplanung, OpenShifts, Zeiterfassung, Verfügbarkeit, Abwesenheiten, Nachrichten, Aufgaben und Stundenzettel in eine mobile App für Teams und Führungskräfte.",
                "keywords": "dienstplan,schicht,zeiterfassung,team,arbeitszeit,stundenzettel",
                "promotional_text": "Dienstplanung und Zeiterfassung für das ganze Team.",
                "release_notes": "Erste Version mit Dienstplan, OpenShifts, Zeiterfassung, Anfragen, Inbox, Team und Stundenzetteln.",
            },
            "en-US": {
                "title": "SchichtPro", "subtitle": "Scheduling & Time Clock",
                "short_description": "Schedule shifts, track time and coordinate your team.",
                "full_description": "SchichtPro combines employee scheduling, OpenShifts, time clock, availability, time off, messaging, tasks and timesheets in one mobile app for employees and managers.",
                "keywords": "schedule,shift,time clock,team,timesheet,workforce",
                "promotional_text": "Scheduling and time tracking for your whole team.",
                "release_notes": "First release with scheduling, OpenShifts, time clock, requests, inbox, team and timesheets.",
            },
        }
        for locale, defaults in entries.items():
            AppLocalization.objects.update_or_create(app=app, locale=locale, defaults=defaults)

    @staticmethod
    def _upsert_compliance(app):
        profile, _ = ComplianceProfile.objects.get_or_create(app=app)
        profile.primary_locale = "de-DE"
        profile.support_email = "support@smarbiz.sbs"
        profile.purpose = "Employee scheduling, workplace time tracking and team coordination."
        profile.business_model = "B2B SaaS; no mobile purchase flow"
        profile.has_ads = False
        profile.target_age_groups = ["18 and over"]
        profile.app_access = "restricted"
        profile.app_access_instructions = "Use the Publisher-managed App Review account; no purchase is required."
        profile.account_deletion = "support"
        profile.account_deletion_url = f"{PUBLIC_URL}/account-deletion"
        profile.payment_handling = "none"
        profile.payment_details = "No purchases or subscriptions are sold inside the mobile app."
        profile.data_practices = {
            "encrypted_in_transit": True, "deletion_request": True, "account_creation": True,
            "data_types": {
                "personal_info.email": {"collected": True, "shared": False, "required": True, "purposes": ["account_management", "app_functionality"]},
                "personal_info.name": {"collected": True, "shared": False, "required": True, "purposes": ["app_functionality"]},
                "location.precise": {"collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "user_content.other": {"collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "diagnostics.other": {"collected": True, "shared": False, "required": False, "purposes": ["fraud_prevention", "app_functionality"]},
            },
        }
        profile.content_rating_answers = {"violence": False, "sexual_content": False, "language": False, "controlled_substances": False, "gambling": False, "user_generated_content": True, "location_sharing": False}
        profile.store_declarations = {"contains_ads": False, "designed_for_children": False, "app_access": "restricted", "privacy_policy_url": app.privacy_policy_url, "account_deletion_url": profile.account_deletion_url}
        profile.unresolved_questions = ["Create the first app record in both store consoles.", "Add a permanent App Review login before submission.", "Capture final screenshots from signed iOS and Android builds."]
        profile.console_autofill = _console_autofill(profile)
        profile.status = "needs_review"
        profile.confidence = 0.95
        profile.save()

    @staticmethod
    def _upsert_release(app, version, build_number):
        release, _ = Release.objects.update_or_create(
            app=app, version_name=version, build_number=build_number,
            defaults={"source_branch": "main", "android_track": "internal", "android_rollout": 1, "ios_release_type": "manual", "auto_submit": False, "release_notes": "Initial SchichtPro mobile release."},
        )
        return release

    def _prepare_signing(self, app):
        try:
            credential = ensure_android_signing(app)
            self.stdout.write(f"android_signing=ready sha256={credential.certificate_sha256}")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"android_signing=blocked {exc}"))
        if not app.apple_account or not app.apple_account.configured:
            self.stdout.write(self.style.WARNING("ios_signing=blocked apple_account_missing"))
            return
        try:
            client = AppleStoreClient(app.apple_account)
            found = client.request("GET", f"/bundleIds?filter[identifier]={APP_ID}&limit=10").get("data", [])
            if not found:
                body = {"data": {"type": "bundleIds", "attributes": {"identifier": APP_ID, "name": "SchichtPro", "platform": "IOS"}}}
                client.request("POST", "/bundleIds", data=__import__("json").dumps(body))
                self.stdout.write("apple_bundle_id=registered")
            profile = ensure_ios_signing(app)
            self.stdout.write(self.style.SUCCESS(f"ios_signing=ready profile={profile.profile_name}"))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"ios_signing=blocked {exc}"))

    def _queue_builds(self, app, release):
        for platform, required in (("android", "linux"), ("ios", "macos")):
            if platform == "ios" and not app.apple_account:
                self.stdout.write(self.style.WARNING("ios_build=blocked apple_account_missing"))
                continue
            build, _ = Build.objects.get_or_create(release=release, platform=platform)
            if build.status == "succeeded" or Job.objects.filter(build=build, type=f"build_{platform}", status__in=["queued", "running"]).exists():
                continue
            build.status = "queued"; build.save(update_fields=["status", "updated_at"])
            Job.objects.create(type=f"build_{platform}", app=app, release=release, build=build, available_to_agents=True, required_platform=required)
            self.stdout.write(self.style.SUCCESS(f"{platform}_build=queued"))

    def _report(self, app, release):
        self.stdout.write(f"schichtpro={app.status} release={release.version_name}({release.build_number})")
        self.stdout.write(f"google_account={'ready' if app.google_account and app.google_account.configured else 'missing'}")
        self.stdout.write(f"apple_account={'ready' if app.apple_account and app.apple_account.configured else 'missing'}")
