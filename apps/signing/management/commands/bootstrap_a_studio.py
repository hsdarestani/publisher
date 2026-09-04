from __future__ import annotations

import io
import json
import textwrap

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from apps.compliance.models import ComplianceProfile
from apps.compliance.services import _console_autofill
from apps.integrations.apple_assets import sync_app_store_screenshots
from apps.integrations.apple_store import AppleStoreClient
from apps.integrations.google_play import GooglePlayClient
from apps.publisher.models import AppAsset, AppLocalization, Build, Job, MobileApp, Release, StoreAccount, Submission
from apps.signing.services import ensure_android_signing, ensure_ios_signing


APP_SLUG = "a-studio"
APP_ID = "de.aplussolution.studio"
APP_REPO = "https://github.com/hsdarestani/a-studio"
PUBLIC_URL = "https://studio.aplus-solution.de"
ASTUDIO_COMMIT = "4269901212bf9822c3f50cf1a190505e6b5cf61d"
CURRENT_BUILD_NUMBER = 9


class Command(BaseCommand):
    help = "Prepare the App Store-safe A+ Studio customer companion, queue Build 9, and advance Apple submission."

    def add_arguments(self, parser):
        parser.add_argument("--app-version", default="1.0.0")
        parser.add_argument("--build-number", type=int, default=CURRENT_BUILD_NUMBER)
        parser.add_argument("--queue", action="store_true")
        parser.add_argument("--publish", action="store_true")
        parser.add_argument("--diagnose-only", action="store_true")

    def handle(self, *args, **options):
        if options["build_number"] < 1:
            raise CommandError("--build-number must be >= 1")
        # The legacy orchestration workflow still passes build 1. Never allow it
        # to roll the App Store remediation back below Build 9.
        build_number = max(int(options["build_number"]), CURRENT_BUILD_NUMBER)

        if options["diagnose_only"]:
            app = MobileApp.objects.filter(slug=APP_SLUG).select_related("google_account", "apple_account").first()
            if not app:
                raise CommandError("A+ Studio is not registered in Publisher yet.")
            release = Release.objects.filter(app=app, version_name=options["app_version"], build_number=build_number).first()
            self._report(app, release)
            return

        with transaction.atomic():
            app = self._upsert_app()
            self._upsert_localizations(app)
            self._upsert_assets(app)
            self._upsert_compliance(app)
            release = self._upsert_release(app, options["app_version"], build_number)

        self._prepare_signing(app)
        if options["queue"]:
            self._queue_builds(app, release)
        if options["publish"]:
            self._advance_publication(app, release)
        self._report(app, release)

    def _configured_account(self, provider: str, current, reference):
        for source in (current, reference):
            account = getattr(source, f"{provider}_account", None) if source else None
            if account and account.enabled and account.configured:
                return account
        return next(
            (item for item in StoreAccount.objects.filter(provider=provider, enabled=True).order_by("created_at") if item.configured),
            None,
        )

    def _upsert_app(self):
        current = MobileApp.objects.filter(slug=APP_SLUG).select_related("google_account", "apple_account").first()
        reference = MobileApp.objects.filter(slug="a-plus-solution").select_related("google_account", "apple_account").first()
        google_account = self._configured_account("google", current, reference)
        apple_account = self._configured_account("apple", current, reference)
        defaults = {
            "name": "A+ Studio",
            "client_name": "A+ Solution GmbH",
            "platform": "both",
            "framework": "other",
            "status": "active",
            "package_name": APP_ID,
            "bundle_id": APP_ID,
            "repository_url": APP_REPO,
            "default_branch": "main",
            "privacy_policy_url": f"{PUBLIC_URL}/mobile/privacy/",
            "support_url": f"{PUBLIC_URL}/mobile/support/",
            "marketing_url": f"{PUBLIC_URL}/mobile/",
            "category": "Business",
            "content_rating": "4+",
            "requires_login": False,
            "review_username": "",
            "review_notes": (
                "Guideline 2.5.2 remediation for Build 9. A+ Studio on iOS is an existing-customer project companion only. "
                "Build 8 exposed cloud app-project creation; that capability has been removed from the iOS product and the "
                "production mobile API. The iOS app does not create software projects, generate or execute code, preview generated "
                "apps, control builds or publishing, submit apps to stores, or download executable content. Accounts and projects "
                "are provisioned outside the iOS app by the A+ Solution project team. Tap 'Demo ansehen' on the sign-in screen to "
                "review the complete iOS feature set without an account. Customer functions are limited to viewing already-assigned "
                "project information and neutral progress and sending text questions or feedback to the human project team."
            ),
            "google_account": google_account,
            "apple_account": apple_account,
            "build_config": {
                "android_command": "bash scripts/build-android.sh",
                "android_artifact": "artifacts/a-studio-release.aab",
                "ios_command": "bash scripts/build-ios.sh",
                "ios_artifact": "artifacts/a-studio.ipa",
                "env": {"REQUIRE_ANDROID_SIGNING": "1"},
            },
            "tech_stack": ["Django API", "Capacitor 8", "JavaScript", "Android", "iOS"],
        }
        app, created = MobileApp.objects.update_or_create(slug=APP_SLUG, defaults=defaults)
        self.stdout.write(f"app={'created' if created else 'updated'}")
        self.stdout.write(f"google_account={'configured' if google_account else 'missing'}")
        self.stdout.write(f"apple_account={'configured' if apple_account else 'missing'}")
        return app

    @staticmethod
    def _de_metadata():
        return {
            "title": "A+ Studio",
            "subtitle": "Kundenprojekte mobil",
            "short_description": "Projektstatus & Abstimmung",
            "full_description": (
                "A+ Studio ist der mobile Kundenbereich für bereits bestehende A+ Solution Projekte. "
                "Sehen Sie Projektstatus, Projektdetails und offene Abstimmungspunkte und senden Sie Fragen oder Feedback an das Projektteam.\n\n"
                "Der mobile Zugang ist ausschließlich für bereits zugeordnete Kundenprojekte gedacht. Konten und Projekte werden "
                "außerhalb der mobilen App durch das A+ Solution Projektteam eingerichtet. Über 'Demo ansehen' auf der Anmeldeseite "
                "kann der vollständige mobile Funktionsumfang ohne Konto geprüft werden.\n\n"
                "Die iOS-App erstellt keine Softwareprojekte, generiert oder führt keinen Code aus, zeigt keine generierten Apps als "
                "Preview an und enthält keine Build-, Publishing- oder Store-Submission-Funktionen. Die App enthält keine Käufe oder Abonnements."
            ),
            "keywords": "projekt,kundenbereich,status,abstimmung,feedback,team",
            "promotional_text": "Bestehende Kundenprojekte mobil im Blick behalten und mit dem Projektteam abstimmen.",
            "release_notes": "Der iOS-Kundenbereich wurde auf Status und Abstimmung für bereits zugeordnete Projekte fokussiert.",
        }

    @staticmethod
    def _en_metadata():
        return {
            "title": "A+ Studio",
            "subtitle": "Customer projects",
            "short_description": "Project status & coordination",
            "full_description": (
                "A+ Studio is the mobile customer area for existing A+ Solution projects. View project status, project details and "
                "open coordination items, and send questions or feedback to the project team.\n\n"
                "Mobile access is only for customer projects already assigned to an account. Accounts and projects are set up outside "
                "the mobile app by the A+ Solution project team. Tap 'Demo ansehen' on the sign-in screen to review the complete mobile "
                "feature set without an account.\n\n"
                "The iOS app does not create software projects, generate or execute code, preview generated apps, or provide build, "
                "publishing or store-submission controls. The app contains no purchases or subscriptions."
            ),
            "keywords": "project,customer,status,coordination,feedback,team",
            "promotional_text": "Keep existing customer projects in view and coordinate with the project team.",
            "release_notes": "The iOS customer area is focused on status and coordination for already assigned projects.",
        }

    def _upsert_localizations(self, app):
        wanted = {"de-DE": self._de_metadata(), "en-US": self._en_metadata()}
        for locale, defaults in wanted.items():
            AppLocalization.objects.update_or_create(app=app, locale=locale, defaults=defaults)
        # Sanitize any previously-created locale as well so old Builder/Preview text
        # cannot survive in App Store Connect through a secondary localization.
        for loc in app.localizations.all():
            values = self._de_metadata() if loc.locale.lower().startswith("de") else self._en_metadata()
            for key, value in values.items():
                setattr(loc, key, value)
            loc.save(update_fields=[*values.keys(), "updated_at"])
        self.stdout.write("store_localizations=companion_only")

    @staticmethod
    def _font(size: int, bold=False):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                pass
        return ImageFont.load_default()

    @classmethod
    def _draw_wrapped(cls, draw, text, xy, width, font, fill, spacing=10):
        words, lines, current = text.split(), [], []
        for word in words:
            trial = " ".join(current + [word])
            if not current or draw.textbbox((0, 0), trial, font=font)[2] <= width:
                current.append(word)
            else:
                lines.append(" ".join(current)); current = [word]
        if current:
            lines.append(" ".join(current))
        y = xy[1]
        for line in lines:
            draw.text((xy[0], y), line, font=font, fill=fill)
            y += draw.textbbox((0, 0), line, font=font)[3] + spacing
        return y

    @classmethod
    def _icon_bytes(cls, size=512):
        image = Image.new("RGB", (size, size), "#0b0c0f")
        draw = ImageDraw.Draw(image)
        draw.ellipse((size * .5, -size * .15, size * 1.15, size * .5), fill="#2a2418")
        pad = int(size * .12)
        draw.rounded_rectangle((pad, pad, size-pad, size-pad), radius=int(size*.16), outline="#3a3d44", width=max(2, size//160), fill="#121419")
        draw.text((size*.20, size*.29), "A", font=cls._font(int(size*.42), True), fill="#e7c66d")
        draw.text((size*.60, size*.21), "+", font=cls._font(int(size*.25), True), fill="#f4f2ea")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    @classmethod
    def _feature_bytes(cls):
        image = Image.new("RGB", (1024, 500), "#0b0c0f")
        draw = ImageDraw.Draw(image)
        draw.ellipse((650, -180, 1120, 290), fill="#292319")
        draw.text((70, 72), "A+ STUDIO", font=cls._font(30, True), fill="#e7c66d")
        draw.text((70, 140), "Kundenprojekte", font=cls._font(60, True), fill="#f4f2ea")
        draw.text((72, 235), "Status  •  Details  •  Abstimmung", font=cls._font(25), fill="#a6abb4")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    @classmethod
    def _screenshot_bytes(cls, width, height, index, title, subtitle, english=False):
        image = Image.new("RGB", (width, height), "#0b0c0f")
        draw = ImageDraw.Draw(image)
        scale = width / 1080
        mx = int(72 * scale)
        draw.ellipse((width*.48, -height*.08, width*1.08, height*.23), fill="#252018")
        draw.text((mx, int(110*scale)), "A+ STUDIO", font=cls._font(int(27*scale), True), fill="#e7c66d")
        y = cls._draw_wrapped(draw, title, (mx, int(185*scale)), width-2*mx, cls._font(int(58*scale), True), "#f5f4f0", int(12*scale))
        y += int(24*scale)
        y = cls._draw_wrapped(draw, subtitle, (mx, y), width-2*mx, cls._font(int(26*scale)), "#a6abb4", int(10*scale)) + int(55*scale)
        card = (mx, y, width-mx, min(height-int(220*scale), y+int(950*scale)))
        draw.rounded_rectangle(card, radius=int(34*scale), fill="#17191e", outline="#30333a", width=max(2, int(2*scale)))
        cx, cy, cw = card[0]+int(34*scale), card[1]+int(38*scale), card[2]-card[0]-int(68*scale)
        if index == 0:
            draw.text((cx, cy), "PROJECTS" if english else "PROJEKTE", font=cls._font(int(20*scale), True), fill="#e7c66d")
            rows = (("Website Relaunch", "In progress" if english else "In Umsetzung"), ("Customer portal" if english else "Kundenportal", "Coordination" if english else "In Abstimmung"), ("Appointment area" if english else "Terminbereich", "Ready" if english else "Bereit"))
            for n, (name, status) in enumerate(rows):
                top = cy + int((105+n*210)*scale)
                draw.rounded_rectangle((cx, top, cx+cw, top+int(165*scale)), radius=int(24*scale), fill="#101216", outline="#282b31")
                draw.text((cx+int(25*scale), top+int(28*scale)), status, font=cls._font(int(18*scale), True), fill="#e7c66d")
                draw.text((cx+int(25*scale), top+int(72*scale)), name, font=cls._font(int(29*scale), True), fill="#f5f4f0")
        elif index == 1:
            draw.text((cx, cy), "PROJECT STATUS" if english else "PROJEKTSTATUS", font=cls._font(int(20*scale), True), fill="#e7c66d")
            rows = (("Briefing", "Done" if english else "Erledigt"), ("Design", "Done" if english else "Erledigt"), ("Implementation" if english else "Umsetzung", "In progress" if english else "In Arbeit"), ("Coordination" if english else "Abstimmung", "Open" if english else "Offen"))
            for n, (key, value) in enumerate(rows):
                top = cy + int((115+n*145)*scale)
                draw.line((cx, top, cx+cw, top), fill="#2d3036", width=max(1, int(scale)))
                draw.text((cx, top+int(30*scale)), key, font=cls._font(int(22*scale)), fill="#9298a2")
                draw.text((cx+int(360*scale), top+int(27*scale)), value, font=cls._font(int(23*scale), True), fill="#f5f4f0")
        elif index == 2:
            draw.text((cx, cy), "COORDINATION" if english else "ABSTIMMUNG", font=cls._font(int(20*scale), True), fill="#e7c66d")
            messages = (("Could you please check the text in the contact section?" if english else "Könnt ihr bitte den Text im Kontaktbereich prüfen?", True), ("Yes. The project team will review it and get back to you here." if english else "Ja. Das Projektteam prüft den Punkt und meldet sich hier zurück.", False))
            top = cy + int(95*scale)
            for text, customer in messages:
                h = int((230 if customer else 270)*scale)
                left = cx + (int(80*scale) if customer else 0)
                right = cx+cw-(0 if customer else int(80*scale))
                draw.rounded_rectangle((left, top, right, top+h), radius=int(24*scale), fill="#d9ba64" if customer else "#23262d")
                cls._draw_wrapped(draw, text, (left+int(24*scale), top+int(28*scale)), right-left-int(48*scale), cls._font(int(23*scale)), "#17130b" if customer else "#f5f4f0", int(9*scale))
                top += h + int(30*scale)
        else:
            draw.text((cx, cy), "CUSTOMER AREA" if english else "KUNDENBEREICH", font=cls._font(int(20*scale), True), fill="#e7c66d")
            labels = (("Assigned projects" if english else "Zugeordnete Projekte", "✓"), ("Project details" if english else "Projektdetails", "✓"), ("Progress" if english else "Fortschritt", "✓"), ("Contact project team" if english else "Projektteam kontaktieren", "✓"))
            for n, (label, mark) in enumerate(labels):
                top = cy + int((115+n*145)*scale)
                draw.ellipse((cx, top, cx+int(52*scale), top+int(52*scale)), fill="#294536")
                draw.text((cx+int(14*scale), top+int(5*scale)), mark, font=cls._font(int(30*scale), True), fill="#72d8a0")
                draw.text((cx+int(82*scale), top+int(7*scale)), label, font=cls._font(int(24*scale), True), fill="#f5f4f0")
        draw.text((mx, height-int(105*scale)), "A+ Solution GmbH", font=cls._font(int(20*scale), True), fill="#777d87")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    def _save_asset(self, app, *, kind, platform, locale, filename, data, width, height, sort_order=0, device_type=""):
        asset = AppAsset.objects.filter(app=app, kind=kind, platform=platform, locale=locale, device_type=device_type, sort_order=sort_order).first()
        if not asset:
            asset = AppAsset(app=app, kind=kind, platform=platform, locale=locale, device_type=device_type, sort_order=sort_order)
        asset.width, asset.height = width, height
        asset.file.save(filename, ContentFile(data), save=True)
        return asset

    def _upsert_assets(self, app):
        self._save_asset(app, kind="icon", platform="shared", locale="de-DE", filename="a-studio-icon-512.png", data=self._icon_bytes(), width=512, height=512)
        self._save_asset(app, kind="feature_graphic", platform="android", locale="de-DE", filename="a-studio-feature-1024x500.png", data=self._feature_bytes(), width=1024, height=500)
        # Remove all previously-generated Builder/Preview screenshots before creating
        # the customer-companion screenshots used for this resubmission.
        AppAsset.objects.filter(app=app, kind="screenshot", platform__in=["ios", "android"]).delete()
        de_frames = [
            ("Bestehende Projekte im Blick.", "Status und Projektdetails für bereits zugeordnete Kundenprojekte."),
            ("Projektstatus klar verfolgen.", "Fortschritt und offene Abstimmungspunkte kompakt ansehen."),
            ("Direkt mit dem Team abstimmen.", "Fragen und Feedback als Text an das A+ Solution Projektteam senden."),
            ("Mobil, ruhig und fokussiert.", "Kundenbereich für Status, Details und persönliche Projektabstimmung."),
        ]
        en_frames = [
            ("Existing projects at a glance.", "Status and project details for customer projects already assigned to you."),
            ("Follow project status clearly.", "See progress and open coordination items in one place."),
            ("Coordinate with the project team.", "Send text questions and feedback to the A+ Solution project team."),
            ("A focused mobile customer area.", "Project status, details and direct project coordination."),
        ]
        for loc in app.localizations.all():
            english = not loc.locale.lower().startswith("de")
            frames = en_frames if english else de_frames
            for index, (title, subtitle) in enumerate(frames):
                self._save_asset(app, kind="screenshot", platform="ios", locale=loc.locale, filename=f"ios-{loc.locale}-{index+1}.png", data=self._screenshot_bytes(1284, 2778, index, title, subtitle, english), width=1284, height=2778, sort_order=index, device_type="APP_IPHONE_65")
                self._save_asset(app, kind="screenshot", platform="android", locale=loc.locale, filename=f"android-{loc.locale}-{index+1}.png", data=self._screenshot_bytes(1080, 1920, index, title, subtitle, english), width=1080, height=1920, sort_order=index, device_type="phone")
        self.stdout.write("store_assets=companion_only")

    def _upsert_compliance(self, app):
        profile, _ = ComplianceProfile.objects.get_or_create(app=app)
        profile.primary_locale = "de-DE"
        profile.support_email = "app@aplus-solution.de"
        profile.purpose = "Mobiler Kundenbereich für bereits zugeordnete A+ Solution Projekte: Status, Projektdetails und Abstimmung mit dem Projektteam."
        profile.business_model = "B2B project companion; no mobile purchase flow"
        profile.has_ads = False
        profile.target_age_groups = ["18 and over"]
        profile.app_access = "restricted"
        profile.app_access_instructions = "App Review kann über 'Demo ansehen' ohne Konto den vollständigen mobilen Funktionsumfang prüfen. Echte Konten und Projekte werden außerhalb der iOS-App durch das Projektteam eingerichtet."
        profile.account_deletion = "in_app"
        profile.account_deletion_url = f"{PUBLIC_URL}/account-deletion/"
        profile.payment_handling = "none"
        profile.payment_details = "Die Mobile-App enthält keine Käufe, Preise, Abonnements oder externen Zahlungslinks."
        profile.data_practices = {
            "encrypted_in_transit": True,
            "deletion_request": True,
            "account_creation": False,
            "data_types": {
                "personal_info.email": {"label": "Email address", "collected": True, "shared": False, "required": False, "purposes": ["account_management", "app_functionality"]},
                "personal_info.name": {"label": "Name", "collected": True, "shared": False, "required": False, "purposes": ["account_management"]},
                "user_ids": {"label": "User IDs", "collected": True, "shared": False, "required": False, "purposes": ["account_management", "app_functionality"]},
                "user_content.other": {"label": "Project feedback", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "diagnostics.other": {"label": "Diagnostics", "collected": True, "shared": False, "required": False, "purposes": ["fraud_prevention", "app_functionality"]},
            },
        }
        profile.content_rating_answers = {"violence": False, "sexual_content": False, "language": False, "controlled_substances": False, "gambling": False, "user_generated_content": False, "location_sharing": False}
        profile.store_declarations = {"contains_ads": False, "target_age_groups": ["18 and over"], "designed_for_children": False, "app_access": "restricted", "privacy_policy_url": f"{PUBLIC_URL}/mobile/privacy/", "account_deletion_url": f"{PUBLIC_URL}/account-deletion/"}
        profile.unresolved_questions = []
        profile.console_autofill = _console_autofill(profile)
        profile.status = "ready"
        profile.confidence = 0.99
        profile.save()
        self.stdout.write("compliance_profile=companion_only")

    def _upsert_release(self, app, version, build_number):
        release, _ = Release.objects.update_or_create(
            app=app, version_name=version, build_number=build_number,
            defaults={
                "status": "building",
                "source_branch": "main",
                "source_commit": ASTUDIO_COMMIT,
                "android_track": "production",
                "android_rollout": 1,
                "ios_release_type": "manual",
                "auto_submit": False,
                "release_notes": "Guideline 2.5.2 remediation: existing-customer project companion only.",
            },
        )
        return release

    def _ensure_apple_bundle_id(self, app):
        if not app.apple_account or not app.apple_account.configured:
            return None
        client = AppleStoreClient(app.apple_account)
        data = client.request("GET", f"/bundleIds?filter[identifier]={APP_ID}&limit=10")
        for item in data.get("data", []):
            if item.get("attributes", {}).get("identifier") == APP_ID:
                return item
        body = {"data": {"type": "bundleIds", "attributes": {"identifier": APP_ID, "name": "A+ Studio", "platform": "IOS"}}}
        return client.request("POST", "/bundleIds", data=json.dumps(body))["data"]

    def _prepare_signing(self, app):
        try:
            credential = ensure_android_signing(app)
            self.stdout.write(f"android_signing=ready sha256={credential.certificate_sha256}")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"android_signing=blocked {exc}"))
        if not app.apple_account or not app.apple_account.configured:
            self.stdout.write(self.style.WARNING("ios_signing=blocked apple_account_missing")); return
        try:
            self._ensure_apple_bundle_id(app)
            profile = ensure_ios_signing(app)
            self.stdout.write(self.style.SUCCESS(f"ios_signing=ready profile={profile.profile_name}"))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"ios_signing=blocked {exc}"))

    def _queue_one(self, app, release, platform):
        build, _ = Build.objects.get_or_create(release=release, platform=platform)
        if build.status == "succeeded":
            self.stdout.write(f"{platform}_build=already_succeeded"); return
        job_type = "build_android" if platform == "android" else "build_ios"
        required = "linux" if platform == "android" else "macos"
        if Job.objects.filter(app=app, release=release, build=build, type=job_type, status__in=["queued", "running"]).exists():
            self.stdout.write(f"{platform}_build=already_queued"); return
        build.status = "queued"; build.logs = ""; build.external_build_id = ""; build.save(update_fields=["status", "logs", "external_build_id", "updated_at"])
        release.status = "building"; release.save(update_fields=["status", "updated_at"])
        Job.objects.create(type=job_type, app=app, release=release, build=build, payload={"source": "a-studio-build9-companion", "expected_commit": ASTUDIO_COMMIT}, available_to_agents=True, required_platform=required)
        self.stdout.write(self.style.SUCCESS(f"{platform}_build=queued"))

    def _queue_builds(self, app, release):
        # Keep the legacy workflow's Android completion condition satisfied, but do
        # not publish Android from this Apple-rejection remediation run.
        self._queue_one(app, release, "android")
        if app.apple_account and app.apple_account.configured:
            self._queue_one(app, release, "ios")

    @staticmethod
    def _job_exists(app, release, build, job_type):
        return Job.objects.filter(app=app, release=release, build=build, type=job_type, status__in=["queued", "running", "succeeded"]).exists()

    def _submit_ios(self, app, release, build):
        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        version = client.ensure_version(record["id"], release.version_name)
        version_id = version["id"]

        remote = client.request("GET", f"/builds/{build.external_build_id}?fields[builds]=version,processingState,usesNonExemptEncryption").get("data") or {}
        attrs = remote.get("attributes", {})
        if attrs.get("processingState") != "VALID":
            self.stdout.write(f"apple_submit=waiting_processing:{attrs.get('processingState')}"); return
        if str(attrs.get("version")) != str(release.build_number):
            raise CommandError(f"Refusing to submit wrong Apple build number: {attrs.get('version')}")
        if attrs.get("usesNonExemptEncryption") is None:
            client.set_build_uses_non_exempt_encryption(build.external_build_id, False)

        for loc in app.localizations.all():
            client.set_localization(version_id, loc)
        sync_app_store_screenshots(client, version_id, app.localizations.all(), app.assets.filter(kind="screenshot", platform="ios"))
        client.attach_build(version_id, build.external_build_id)
        client.set_review_details(version_id, app, contact=None)

        infos = client.request("GET", f"/apps/{record['id']}/appInfos?limit=10").get("data") or []
        if infos:
            info_id = infos[0]["id"]
            for loc in app.localizations.all():
                rows = client.request("GET", f"/appInfos/{info_id}/appInfoLocalizations?filter[locale]={loc.locale}&limit=1").get("data") or []
                if not rows:
                    continue
                row = rows[0]
                patch = {"privacyPolicyUrl": app.privacy_policy_url}
                if loc.subtitle:
                    patch["subtitle"] = loc.subtitle
                body = {"data": {"type": "appInfoLocalizations", "id": row["id"], "attributes": patch}}
                client.request("PATCH", f"/appInfoLocalizations/{row['id']}", data=json.dumps(body))

        # Reuse and resolve the rejected Build 8 review submission for version 1.0.0.
        final = None
        for submission in client.list_review_submissions(record["id"], "UNRESOLVED_ISSUES"):
            item, _ = client._review_submission_matches(submission, version_id)
            if not item:
                continue
            if item.get("attributes", {}).get("state") == "REJECTED":
                body = {"data": {"type": "reviewSubmissionItems", "id": item["id"], "attributes": {"resolved": True}}}
                client.request("PATCH", f"/reviewSubmissionItems/{item['id']}", data=json.dumps(body))
            body = {"data": {"type": "reviewSubmissions", "id": submission["id"], "attributes": {"submitted": True}}}
            final = client.request("PATCH", f"/reviewSubmissions/{submission['id']}", data=json.dumps(body))["data"]
            break
        if final is None:
            result = client.submit_version(record["id"], version_id)
            final = result["submission"]

        state = final.get("attributes", {}).get("state", "")
        Submission.objects.update_or_create(app=app, release=release, platform="ios", defaults={"state": "in_review", "external_id": final["id"], "submitted_at": timezone.now(), "last_error": "", "raw": {"submission": final, "build_number": release.build_number, "guideline_2_5_2_remediation": True, "review_mode": "local_demo_no_login"}})
        release.status = "in_review"; release.save(update_fields=["status", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"APPLE_REVIEW|build={release.build_number}|state={state}|submission={final['id']}"))

    def _advance_publication(self, app, release):
        # This run is specifically for the Apple rejection. Do not mutate Google Play.
        android = release.builds.filter(platform="android", status="succeeded").first()
        if android:
            self.stdout.write("google_publish=skipped_ios_remediation")

        ios = release.builds.filter(platform="ios", status="succeeded").first()
        if not ios:
            return
        if not app.apple_account or not app.apple_account.configured:
            self.stdout.write(self.style.WARNING("apple_publish=blocked apple_account_missing")); return
        if not ios.external_build_id:
            if not self._job_exists(app, release, ios, "upload_apple"):
                Job.objects.create(type="upload_apple", app=app, release=release, build=ios, payload={"source": "a-studio-build9-companion"}, available_to_agents=True, required_platform="macos")
                self.stdout.write(self.style.SUCCESS("apple_upload=queued"))
            else:
                self.stdout.write("apple_upload=already_queued")
            return
        if Submission.objects.filter(app=app, release=release, platform="ios", state="in_review").exists():
            self.stdout.write("apple_submit=already_in_review"); return
        self._submit_ios(app, release, ios)

    def _report(self, app, release):
        self.stdout.write("--- a-studio-status ---")
        self.stdout.write(f"app_id={app.pk} package={app.package_name} bundle={app.bundle_id}")
        self.stdout.write("mobile_positioning=existing_customer_project_companion")
        self.stdout.write(f"source_commit={ASTUDIO_COMMIT}")
        if release:
            self.stdout.write(f"release={release.version_name}({release.build_number}) status={release.status}")
            seen = set()
            for build in release.builds.order_by("platform"):
                seen.add(build.platform)
                self.stdout.write(f"build_{build.platform}={build.status} artifact={'yes' if build.artifact else 'no'} external_id={build.external_build_id or '-'}")
            # The release workflow greps these status lines while polling.
            for platform in ("android", "ios"):
                if platform not in seen:
                    self.stdout.write(f"build_{platform}=missing artifact=no external_id=-")
            for job in release.jobs.order_by("created_at"):
                self.stdout.write(f"job={job.type}:{job.status} error={textwrap.shorten(job.error or '-', width=500, placeholder='...')}")
