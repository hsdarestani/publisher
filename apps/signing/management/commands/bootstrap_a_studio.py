from __future__ import annotations

import io
import json
import textwrap

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageDraw, ImageFont

from apps.compliance.models import ComplianceProfile
from apps.compliance.services import _console_autofill
from apps.integrations.apple_store import AppleStoreClient
from apps.integrations.base import IntegrationError
from apps.integrations.google_play import GooglePlayClient
from apps.publisher.models import AppAsset, AppLocalization, Build, Job, MobileApp, Release, StoreAccount
from apps.publisher.tasks import enqueue_job
from apps.signing.services import ensure_android_signing, ensure_ios_signing


APP_SLUG = "a-studio"
APP_ID = "de.aplussolution.studio"
APP_REPO = "https://github.com/hsdarestani/a-studio"
PUBLIC_URL = "https://studio.aplus-solution.de"


class Command(BaseCommand):
    help = "Create/update A+ Studio in Publisher, prepare store assets/signing, queue builds and advance store submission."

    def add_arguments(self, parser):
        parser.add_argument("--app-version", default="1.0.0")
        parser.add_argument("--build-number", type=int, default=1)
        parser.add_argument("--queue", action="store_true", help="Queue Android and iOS release builds.")
        parser.add_argument("--publish", action="store_true", help="Advance successful builds into real store upload/submission when store records exist.")
        parser.add_argument("--diagnose-only", action="store_true", help="Do not modify app metadata; only print current state and store-record access.")

    def handle(self, *args, **options):
        if options["build_number"] < 1:
            raise CommandError("--build-number must be >= 1")

        if options["diagnose_only"]:
            app = MobileApp.objects.filter(slug=APP_SLUG).select_related("google_account", "apple_account").first()
            if not app:
                raise CommandError("A+ Studio is not registered in Publisher yet.")
            release = Release.objects.filter(app=app, version_name=options["app_version"], build_number=options["build_number"]).first()
            self._report(app, release)
            return

        with transaction.atomic():
            app = self._upsert_app()
            self._upsert_localization(app)
            self._upsert_assets(app)
            self._upsert_compliance(app)
            release = self._upsert_release(app, options["app_version"], options["build_number"])

        self._prepare_signing(app)
        if options["queue"]:
            self._queue_builds(app, release)
        if options["publish"]:
            self._advance_publication(app, release)
        self._report(app, release)

    def _configured_account(self, provider: str, reference):
        account = getattr(reference, f"{provider}_account", None) if reference else None
        if account and account.enabled and account.configured:
            return account
        return next(
            (
                item
                for item in StoreAccount.objects.filter(provider=provider, enabled=True).order_by("created_at")
                if item.configured
            ),
            None,
        )

    def _upsert_app(self):
        reference = MobileApp.objects.filter(slug="a-plus-solution").select_related("google_account", "apple_account").first()
        google_account = self._configured_account("google", reference)
        apple_account = self._configured_account("apple", reference)
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
            "privacy_policy_url": f"{PUBLIC_URL}/privacy/",
            "support_url": f"{PUBLIC_URL}/support/",
            "marketing_url": f"{PUBLIC_URL}/",
            "category": "Business",
            "content_rating": "4+",
            "requires_login": False,
            "review_username": "",
            "review_notes": (
                "Kein bestehendes kostenpflichtiges Konto erforderlich. Auf dem Login-Screen steht 'Demo ansehen' für eine "
                "lokale, vollständig navigierbare Review-Demo zur Verfügung. Alternativ kann in der App kostenlos ein Konto "
                "mit Start-Credits erstellt werden; dafür ist kein Kauf erforderlich. Version 1.0 enthält keine In-App-Käufe, "
                "keine Stripe-Links, keine Werbung und kein Cross-App-Tracking. Die Kontolöschung befindet sich unter "
                "Konto > Konto dauerhaft löschen."
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

    def _upsert_localization(self, app):
        AppLocalization.objects.update_or_create(
            app=app,
            locale="de-DE",
            defaults={
                "title": "A+ Studio",
                "subtitle": "Apps mit AI bauen",
                "short_description": "Apps mit AI planen, als Preview testen und mit A+ professionell veröffentlichen.",
                "full_description": (
                    "A+ Studio ist die mobile AI Software Factory von A+ Solution. Beschreiben Sie Ihre App-Idee, erstellen Sie "
                    "einen ersten Preview-Build und verbessern Sie das Produkt direkt im AI Builder.\n\n"
                    "Verwalten Sie Projekte, verfolgen Sie Build-Status und Versionen, öffnen Sie Previews und starten Sie nach "
                    "Ihrer Freigabe die Veröffentlichung. Für Projekte, die in Apple App Store oder Google Play erscheinen sollen, "
                    "können Sie den A+ Store-Publishing-Prozess direkt aus dem Projekt anstoßen.\n\n"
                    "Die mobile App konzentriert sich auf den produktiven Builder-Workflow: Konto, Projekte, AI-Änderungen, Preview, "
                    "Publishing und Store-Anfragen. Digitale Käufe oder externe Zahlungslinks sind in Version 1.0 bewusst nicht Bestandteil der mobilen App."
                ),
                "keywords": "app builder,ai,ki,software,pwa,prototyp,entwicklung,digitalisierung,preview,business",
                "promotional_text": "Von der Idee zum Preview: Apps mit AI planen, iterieren und mit A+ strukturiert veröffentlichen.",
                "release_notes": "Erste Version von A+ Studio mit AI Builder, Projektverwaltung, Preview, Publishing und Store-Anfragen.",
            },
        )

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
                continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    @classmethod
    def _draw_wrapped(cls, draw, text, xy, width, font, fill, spacing=10):
        words = text.split()
        lines, current = [], []
        for word in words:
            trial = " ".join(current + [word])
            if draw.textbbox((0, 0), trial, font=font)[2] <= width or not current:
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
        draw.rounded_rectangle((pad, pad, size - pad, size - pad), radius=int(size * .16), outline="#3a3d44", width=max(2, size // 160), fill="#121419")
        draw.text((size * .20, size * .29), "A", font=cls._font(int(size * .42), True), fill="#e7c66d")
        draw.text((size * .60, size * .21), "+", font=cls._font(int(size * .25), True), fill="#f4f2ea")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    @classmethod
    def _feature_bytes(cls):
        w, h = 1024, 500
        image = Image.new("RGB", (w, h), "#0b0c0f")
        draw = ImageDraw.Draw(image)
        draw.ellipse((650, -180, 1120, 290), fill="#292319")
        draw.text((70, 72), "A+ STUDIO", font=cls._font(30, True), fill="#e7c66d")
        draw.text((70, 130), "Von der Idee", font=cls._font(62, True), fill="#f4f2ea")
        draw.text((70, 205), "zum App-Preview.", font=cls._font(62, True), fill="#f4f2ea")
        draw.text((72, 315), "AI Builder  •  Preview  •  Publishing", font=cls._font(24), fill="#a6abb4")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    @classmethod
    def _screenshot_bytes(cls, width, height, index, title, subtitle):
        image = Image.new("RGB", (width, height), "#0b0c0f")
        draw = ImageDraw.Draw(image)
        scale = width / 1080
        mx = int(72 * scale)
        draw.ellipse((width * .48, -height * .08, width * 1.08, height * .23), fill="#252018")
        draw.text((mx, int(110 * scale)), "A+ STUDIO", font=cls._font(int(27 * scale), True), fill="#e7c66d")
        y = int(185 * scale)
        y = cls._draw_wrapped(draw, title, (mx, y), width - 2 * mx, cls._font(int(62 * scale), True), "#f5f4f0", int(12 * scale))
        y += int(26 * scale)
        y = cls._draw_wrapped(draw, subtitle, (mx, y), width - 2 * mx, cls._font(int(27 * scale)), "#a6abb4", int(10 * scale))
        y += int(55 * scale)

        card = (mx, y, width - mx, min(height - int(220 * scale), y + int(930 * scale)))
        draw.rounded_rectangle(card, radius=int(34 * scale), fill="#17191e", outline="#30333a", width=max(2, int(2 * scale)))
        cx = card[0] + int(34 * scale); cy = card[1] + int(38 * scale); cw = card[2] - card[0] - int(68 * scale)
        if index == 0:
            draw.text((cx, cy), "WORKSPACE", font=cls._font(int(20 * scale), True), fill="#e7c66d")
            draw.text((cx, cy + int(58 * scale)), "A+ Solution", font=cls._font(int(42 * scale), True), fill="#ffffff")
            for n, (name, status) in enumerate((("Luna Booking", "Preview bereit"), ("Service Portal", "Live"), ("Sales App", "Build läuft"))):
                top = cy + int((170 + n * 205) * scale)
                draw.rounded_rectangle((cx, top, cx + cw, top + int(165 * scale)), radius=int(24 * scale), fill="#101216", outline="#282b31")
                draw.text((cx + int(25 * scale), top + int(28 * scale)), status, font=cls._font(int(18 * scale), True), fill="#72d8a0" if n < 2 else "#e7c66d")
                draw.text((cx + int(25 * scale), top + int(72 * scale)), name, font=cls._font(int(30 * scale), True), fill="#f5f4f0")
        elif index == 1:
            draw.text((cx, cy), "AI BUILDER", font=cls._font(int(20 * scale), True), fill="#e7c66d")
            bubbles = [
                ("Füge eine übersichtliche Wochenansicht für Termine hinzu.", True),
                ("Erledigt. Der neue Preview-Build enthält Tagesnavigation, freie Slots und eine kompakte Terminübersicht.", False),
            ]
            top = cy + int(90 * scale)
            for text, user in bubbles:
                box_h = int((220 if user else 310) * scale)
                left = cx + (int(90 * scale) if user else 0)
                right = cx + cw - (0 if user else int(90 * scale))
                draw.rounded_rectangle((left, top, right, top + box_h), radius=int(24 * scale), fill="#d9ba64" if user else "#23262d")
                cls._draw_wrapped(draw, text, (left + int(25 * scale), top + int(28 * scale)), right-left-int(50 * scale), cls._font(int(24 * scale)), "#17130b" if user else "#f5f4f0", int(9 * scale))
                top += box_h + int(28 * scale)
        elif index == 2:
            draw.text((cx, cy), "BUILD", font=cls._font(int(20 * scale), True), fill="#e7c66d")
            draw.text((cx, cy + int(62 * scale)), "Preview bereit", font=cls._font(int(44 * scale), True), fill="#72d8a0")
            rows = (("Version", "3"), ("Status", "Preview"), ("Deployment", "Erfolgreich"), ("Nächster Schritt", "Live veröffentlichen"))
            for n, (key, value) in enumerate(rows):
                top = cy + int((180 + n * 135) * scale)
                draw.line((cx, top, cx + cw, top), fill="#2d3036", width=max(1, int(scale)))
                draw.text((cx, top + int(32 * scale)), key, font=cls._font(int(20 * scale)), fill="#9298a2")
                draw.text((cx + int(320 * scale), top + int(26 * scale)), value, font=cls._font(int(24 * scale), True), fill="#f5f4f0")
        else:
            draw.text((cx, cy), "STORE PUBLISHING", font=cls._font(int(20 * scale), True), fill="#e7c66d")
            draw.text((cx, cy + int(62 * scale)), "A+ prüft vor dem Submit.", font=cls._font(int(36 * scale), True), fill="#f5f4f0")
            checks = ("Store-Metadaten", "Signierung & Build", "Datenschutz & Compliance", "Apple + Google Submission")
            for n, label in enumerate(checks):
                top = cy + int((180 + n * 145) * scale)
                draw.ellipse((cx, top, cx + int(52 * scale), top + int(52 * scale)), fill="#294536")
                draw.text((cx + int(14 * scale), top + int(5 * scale)), "✓", font=cls._font(int(30 * scale), True), fill="#72d8a0")
                draw.text((cx + int(82 * scale), top + int(7 * scale)), label, font=cls._font(int(25 * scale), True), fill="#f5f4f0")
        draw.text((mx, height - int(105 * scale)), "A+ Solution GmbH", font=cls._font(int(20 * scale), True), fill="#777d87")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    def _save_asset(self, app, *, kind, platform, filename, data, width, height, sort_order=0, device_type=""):
        asset = AppAsset.objects.filter(
            app=app, kind=kind, platform=platform, locale="de-DE", device_type=device_type, sort_order=sort_order
        ).first()
        if asset:
            return asset
        asset = AppAsset(
            app=app, kind=kind, platform=platform, locale="de-DE", device_type=device_type,
            sort_order=sort_order, width=width, height=height,
        )
        asset.file.save(filename, ContentFile(data), save=True)
        return asset

    def _upsert_assets(self, app):
        self._save_asset(app, kind="icon", platform="shared", filename="a-studio-icon-512.png", data=self._icon_bytes(), width=512, height=512)
        self._save_asset(app, kind="feature_graphic", platform="android", filename="a-studio-feature-1024x500.png", data=self._feature_bytes(), width=1024, height=500)
        frames = [
            ("Alle Projekte. Ein Workspace.", "Status, Credits und Ihre laufenden Produkte jederzeit im Blick."),
            ("Änderungen einfach beschreiben.", "Der AI Builder setzt Anforderungen um und erstellt den nächsten Preview-Build."),
            ("Preview prüfen. Dann live.", "Versionen und Deployments bleiben nachvollziehbar, bevor Sie veröffentlichen."),
            ("Bereit für Apple und Google.", "Store-Anfrage starten und den A+ Publishing-Prozess strukturiert verfolgen."),
        ]
        for index, (title, subtitle) in enumerate(frames):
            self._save_asset(
                app, kind="screenshot", platform="android", filename=f"android-{index+1}.png",
                data=self._screenshot_bytes(1080, 1920, index, title, subtitle), width=1080, height=1920,
                sort_order=index, device_type="phone",
            )
            self._save_asset(
                app, kind="screenshot", platform="ios", filename=f"ios-{index+1}.png",
                data=self._screenshot_bytes(1284, 2778, index, title, subtitle), width=1284, height=2778,
                sort_order=index, device_type="APP_IPHONE_65",
            )
        self.stdout.write("store_assets=ready")

    def _upsert_compliance(self, app):
        profile, _ = ComplianceProfile.objects.get_or_create(app=app)
        profile.primary_locale = "de-DE"
        profile.support_email = "app@aplus-solution.de"
        profile.purpose = "AI-gestützte Planung, Erstellung, Preview, Verwaltung und Veröffentlichung eigener Software-Projekte."
        profile.business_model = "B2B digital service; mobile version 1.0 has no purchase flow"
        profile.has_ads = False
        profile.target_age_groups = ["18 and over"]
        profile.app_access = "restricted"
        profile.app_access_instructions = (
            "Die Review-Demo ist über 'Demo ansehen' ohne Konto verfügbar. Für echte Builds kann direkt in der App kostenlos "
            "ein Konto mit Start-Credits erstellt werden; kein Kauf ist erforderlich."
        )
        profile.account_deletion = "in_app"
        profile.account_deletion_url = f"{PUBLIC_URL}/account-deletion/"
        profile.payment_handling = "none"
        profile.payment_details = "Version 1.0 der Mobile-App enthält keine Käufe, Preise oder externen Zahlungslinks."
        profile.data_practices = {
            "encrypted_in_transit": True,
            "deletion_request": True,
            "account_creation": True,
            "data_types": {
                "personal_info.email": {"label": "Email address", "collected": True, "shared": False, "required": False, "purposes": ["account_management", "app_functionality"]},
                "personal_info.name": {"label": "Name", "collected": True, "shared": False, "required": False, "purposes": ["account_management"]},
                "user_ids": {"label": "User IDs", "collected": True, "shared": False, "required": False, "purposes": ["account_management", "app_functionality"]},
                "user_content.other": {"label": "Other user-generated content", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "diagnostics.other": {"label": "Diagnostics", "collected": True, "shared": False, "required": False, "purposes": ["fraud_prevention", "app_functionality"]},
            },
        }
        profile.content_rating_answers = {
            "violence": False,
            "sexual_content": False,
            "language": False,
            "controlled_substances": False,
            "gambling": False,
            "user_generated_content": False,
            "location_sharing": False,
        }
        profile.store_declarations = {
            "contains_ads": False,
            "target_age_groups": ["18 and over"],
            "designed_for_children": False,
            "app_access": "restricted",
            "privacy_policy_url": f"{PUBLIC_URL}/privacy/",
            "account_deletion_url": f"{PUBLIC_URL}/account-deletion/",
        }
        profile.unresolved_questions = [
            "Google Play: first app record and Play Console-only declarations must exist before API submission.",
            "Google Play: import the current Data Safety CSV template once if API-based Data Safety submission is desired.",
            "Apple: create the first App Store Connect app record; Apple does not expose creation through App Store Connect API.",
        ]
        profile.console_autofill = _console_autofill(profile)
        profile.status = "needs_review"
        profile.confidence = 0.95
        profile.save()
        self.stdout.write("compliance_profile=ready")

    def _upsert_release(self, app, version, build_number):
        release, _ = Release.objects.update_or_create(
            app=app, version_name=version, build_number=build_number,
            defaults={
                "source_branch": "main",
                "android_track": "production",
                "android_rollout": 1,
                "ios_release_type": "manual",
                "auto_submit": False,
                "release_notes": "Erste Version von A+ Studio: AI Builder, Projekte, Preview, Publishing und Store-Anfragen.",
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
                self.stdout.write("apple_bundle_id=existing")
                return item
        body = {
            "data": {
                "type": "bundleIds",
                "attributes": {"identifier": APP_ID, "name": "A+ Studio", "platform": "IOS"},
            }
        }
        item = client.request("POST", "/bundleIds", data=json.dumps(body))["data"]
        self.stdout.write(self.style.SUCCESS("apple_bundle_id=registered"))
        return item

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
            self._ensure_apple_bundle_id(app)
            profile = ensure_ios_signing(app)
            self.stdout.write(self.style.SUCCESS(f"ios_signing=ready profile={profile.profile_name}"))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"ios_signing=blocked {exc}"))

    def _queue_one(self, app, release, platform):
        build, _ = Build.objects.get_or_create(release=release, platform=platform)
        if build.status == "succeeded":
            self.stdout.write(f"{platform}_build=already_succeeded")
            return
        job_type = "build_android" if platform == "android" else "build_ios"
        required = "linux" if platform == "android" else "macos"
        if Job.objects.filter(app=app, release=release, build=build, type=job_type, status__in=["queued", "running"]).exists():
            self.stdout.write(f"{platform}_build=already_queued")
            return
        build.status = "queued"; build.logs = ""; build.save(update_fields=["status", "logs", "updated_at"])
        release.status = "building"; release.save(update_fields=["status", "updated_at"])
        Job.objects.create(
            type=job_type, app=app, release=release, build=build,
            payload={"source": "a-studio-bootstrap"}, available_to_agents=True, required_platform=required,
        )
        self.stdout.write(self.style.SUCCESS(f"{platform}_build=queued"))

    def _queue_builds(self, app, release):
        self._queue_one(app, release, "android")
        if app.apple_account and app.apple_account.configured:
            self._queue_one(app, release, "ios")

    def _store_records(self, app):
        result = {"google": {"ready": False, "message": "account missing"}, "apple": {"ready": False, "message": "account missing"}}
        if app.google_account and app.google_account.configured:
            probe = GooglePlayClient(app.google_account).test(app.package_name)
            result["google"] = {"ready": bool(probe.ok), "message": probe.message, "data": probe.data}
        if app.apple_account and app.apple_account.configured:
            try:
                record = AppleStoreClient(app.apple_account).find_app(app.bundle_id)
                result["apple"] = {"ready": True, "message": "App Store Connect app record found.", "id": record["id"]}
            except Exception as exc:
                result["apple"] = {"ready": False, "message": str(exc)}
        return result

    def _job_exists(self, app, release, build, job_type):
        return Job.objects.filter(
            app=app, release=release, build=build, type=job_type, status__in=["queued", "running", "succeeded"]
        ).exists()

    def _advance_publication(self, app, release):
        records = self._store_records(app)
        android = release.builds.filter(platform="android", status="succeeded").first()
        if android and records["google"]["ready"]:
            if not self._job_exists(app, release, android, "upload_google"):
                enqueue_job("upload_google", app=app, release=release, build=android)
                self.stdout.write(self.style.SUCCESS("google_publish=queued"))
            else:
                self.stdout.write("google_publish=already_live")
        elif android:
            self.stdout.write(self.style.WARNING("google_publish=blocked store_record_or_api_access"))

        ios = release.builds.filter(platform="ios", status="succeeded").first()
        if ios and records["apple"]["ready"]:
            if not ios.external_build_id:
                if not self._job_exists(app, release, ios, "upload_apple"):
                    Job.objects.create(
                        type="upload_apple", app=app, release=release, build=ios,
                        payload={"source": "a-studio-bootstrap"}, available_to_agents=True, required_platform="macos",
                    )
                    self.stdout.write(self.style.SUCCESS("apple_upload=queued"))
                else:
                    self.stdout.write("apple_upload=already_live")
            elif not self._job_exists(app, release, ios, "submit_apple"):
                enqueue_job("submit_apple", app=app, release=release, build=ios)
                self.stdout.write(self.style.SUCCESS("apple_submit=queued"))
            else:
                self.stdout.write("apple_submit=already_live")
        elif ios:
            self.stdout.write(self.style.WARNING("apple_publish=blocked app_store_connect_record_missing"))

    def _report(self, app, release):
        records = self._store_records(app)
        self.stdout.write("--- a-studio-status ---")
        self.stdout.write(f"app_id={app.pk} package={app.package_name} bundle={app.bundle_id}")
        self.stdout.write(f"google_record={'ready' if records['google']['ready'] else 'blocked'}")
        self.stdout.write(textwrap.shorten(f"google_detail={records['google']['message']}", width=900, placeholder="..."))
        self.stdout.write(f"apple_record={'ready' if records['apple']['ready'] else 'blocked'}")
        self.stdout.write(textwrap.shorten(f"apple_detail={records['apple']['message']}", width=900, placeholder="..."))
        if release:
            self.stdout.write(f"release={release.version_name}({release.build_number}) status={release.status}")
            for build in release.builds.order_by("platform"):
                self.stdout.write(
                    f"build_{build.platform}={build.status} artifact={'yes' if build.artifact else 'no'} external_id={build.external_build_id or '-'}"
                )
            for job in release.jobs.order_by("created_at"):
                self.stdout.write(f"job={job.type}:{job.status} error={textwrap.shorten(job.error or '-', width=500, placeholder='...')}")
