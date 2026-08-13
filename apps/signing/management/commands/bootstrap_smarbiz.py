from __future__ import annotations

import io
import json
from secrets import token_hex, token_urlsafe
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.management.base import CommandError
from django.db import transaction
from PIL import Image, ImageDraw

from apps.compliance.models import ComplianceProfile
from apps.compliance.services import _console_autofill
from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import AppLocalization, MobileApp, Release
from apps.signing.management.commands.bootstrap_a_studio import Command as AStudioCommand

APP_SLUG = "smarbiz"
APP_ID = "de.aplussolution.smarbiz"
APP_REPO = "https://github.com/hsdarestani/BrandFlowAI"
PUBLIC_URL = "https://smarbiz.sbs"


class Command(AStudioCommand):
    help = "Create/update Smarbiz in Publisher, prepare store assets/signing, queue native builds and advance store submission."

    def handle(self, *args, **options):
        if options["build_number"] < 1:
            raise CommandError("--build-number must be >= 1")
        if options["diagnose_only"]:
            app = MobileApp.objects.filter(slug=APP_SLUG).select_related("google_account", "apple_account").first()
            if not app:
                raise CommandError("Smarbiz is not registered in Publisher yet.")
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

    def _upsert_app(self):
        reference = MobileApp.objects.filter(slug="a-plus-solution").select_related("google_account", "apple_account").first()
        google_account = self._configured_account("google", reference)
        apple_account = self._configured_account("apple", reference)
        app, _ = MobileApp.objects.update_or_create(
            slug=APP_SLUG,
            defaults={
                "name": "Smarbiz",
                "client_name": "A+ Solution GmbH",
                "platform": "both",
                "framework": "other",
                "status": "active",
                "package_name": APP_ID,
                "bundle_id": APP_ID,
                "repository_url": APP_REPO,
                "default_branch": "main",
                "privacy_policy_url": f"{PUBLIC_URL}/de/privacy",
                "support_url": f"{PUBLIC_URL}/de/support",
                "marketing_url": f"{PUBLIC_URL}/de",
                "category": "Business",
                "content_rating": "4+ / Everyone",
                "requires_login": True,
                "review_notes": (
                    "Smarbiz is a B2B content and brand workspace. No purchase is required for App Review. "
                    "Use the Publisher-managed review account. Core flow: Dashboard → Brand Pulse → Content Studio → "
                    "Approvals → Calendar → Reports. Permanent deletion is available from Settings → Account deletion."
                ),
                "google_account": google_account,
                "apple_account": apple_account,
                "build_config": {
                    "android_command": "bash apps/mobile/scripts/build-android.sh",
                    "android_artifact": "apps/mobile/artifacts/smarbiz-release.aab",
                    "ios_command": "bash apps/mobile/scripts/build-ios.sh",
                    "ios_artifact": "apps/mobile/artifacts/smarbiz.ipa",
                    "env": {"REQUIRE_ANDROID_SIGNING": "1"},
                },
                "tech_stack": ["Next.js", "FastAPI", "Capacitor 8", "Android", "iOS"],
            },
        )
        self._ensure_review_account(app)
        self.stdout.write(f"publisher_app={app.pk} google_account={getattr(google_account, 'pk', None)} apple_account={getattr(apple_account, 'pk', None)} review_user={'ready' if app.review_username else 'missing'}")
        return app

    def _ensure_review_account(self, app):
        if app.review_username and app.get_review_password():
            return
        email = f"smarbiz-review-{token_hex(4)}@aplus-solution.de"
        password = f"Sb-{token_urlsafe(13)}-A9!"
        payload = json.dumps({
            "name": "App Review",
            "organization_name": "Smarbiz App Review",
            "email": email,
            "password": password,
            "preferred_language": "en",
            "locale": "en",
        }).encode("utf-8")
        request = Request(
            f"{PUBLIC_URL}/api/auth/signup",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "APlusPublisher/1.0"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                if response.status not in {200, 201}:
                    raise RuntimeError(f"unexpected HTTP {response.status}")
            app.review_username = email
            app.set_review_password(password)
            app.save(update_fields=["review_username", "review_password_blob", "updated_at"])
            self.stdout.write(self.style.SUCCESS("review_account=created"))
        except (HTTPError, URLError, RuntimeError) as exc:
            self.stdout.write(self.style.WARNING(f"review_account=blocked {exc}"))

    def _upsert_localization(self, app):
        entries = {
            "de-DE": {
                "title": "Smarbiz",
                "subtitle": "KI für Content & Marke",
                "short_description": "Content planen, erstellen, freigeben und auswerten – in einem Marken-Workspace.",
                "full_description": (
                    "Smarbiz ist der zentrale Workspace für Marken, Marketingteams und Agenturen. Planen Sie Kampagnen, "
                    "erstellen Sie markenkonforme Entwürfe mit KI-Unterstützung, sammeln Sie Freigaben und behalten Sie "
                    "Kalender, Publishing und Ergebnisse an einem Ort im Blick.\n\n"
                    "• Brand Pulse für Zielgruppe, Tonalität und Markenregeln\n"
                    "• Content Studio für Entwürfe, Varianten und Qualitätschecks\n"
                    "• Kampagnen und Content-Kalender für strukturierte Planung\n"
                    "• Freigabe-Workflow mit öffentlichem Review-Link und verbundenen Kanälen\n"
                    "• Reports und Insights für die nächste Content-Runde\n"
                    "• Deutsch, Englisch und Persisch in einem Workspace\n\n"
                    "Smarbiz ist ein B2B-Dienst von A+ Solution GmbH. Die mobile App enthält keine In-App-Käufe."
                ),
                "keywords": "content,marketing,ki,marke,kalender,kampagne,freigabe,agentur,planung,reports",
                "promotional_text": "Von der Markenstrategie bis zur Freigabe: Content-Arbeit in einem klaren Workspace.",
                "release_notes": "Erste mobile Version von Smarbiz mit Brand Pulse, Content Studio, Freigaben, Kalender und Reports.",
            },
            "en-US": {
                "title": "Smarbiz",
                "subtitle": "AI Content Workspace",
                "short_description": "Plan, create, approve and review brand content from one focused workspace.",
                "full_description": (
                    "Smarbiz is a content and brand workspace for businesses, marketing teams and agencies. Plan campaigns, "
                    "create on-brand drafts with AI assistance, collect approvals and keep your calendar, publishing workflow "
                    "and performance insights together.\n\n"
                    "• Brand Pulse for audience, tone and brand rules\n"
                    "• Content Studio for drafts, variants and quality checks\n"
                    "• Campaigns and content calendar for structured planning\n"
                    "• Approval workflows and secure review links\n"
                    "• Reports and insights for continuous improvement\n"
                    "• German, English and Persian interface support\n\n"
                    "Smarbiz is a B2B service by A+ Solution GmbH. The mobile app contains no in-app purchases."
                ),
                "keywords": "content,marketing,ai,brand,calendar,campaign,approval,agency,planning,reports",
                "promotional_text": "Move from brand context to approved content in one clear workspace.",
                "release_notes": "First Smarbiz mobile release with Brand Pulse, Content Studio, approvals, calendar and reports.",
            },
        }
        for locale, defaults in entries.items():
            AppLocalization.objects.update_or_create(app=app, locale=locale, defaults=defaults)
        self.stdout.write("store_localization=ready")

    @staticmethod
    def _gradient(width, height):
        image = Image.new("RGB", (width, height))
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                t = (x / max(1, width - 1) + y / max(1, height - 1)) / 2
                pixels[x, y] = (int(37 + 87 * t), int(99 - 41 * t), int(235 - 25 * t))
        return image

    @classmethod
    def _icon_bytes(cls):
        image = cls._gradient(512, 512)
        draw = ImageDraw.Draw(image)
        draw.text((256, 244), "S", anchor="mm", font=cls._font(270, True), fill="#ffffff")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    @classmethod
    def _feature_bytes(cls):
        image = cls._gradient(1024, 500); draw = ImageDraw.Draw(image)
        draw.text((70, 72), "SMARBIZ", font=cls._font(34, True), fill="#dbeafe")
        draw.text((70, 142), "Content. Freigaben. Kalender.", font=cls._font(53, True), fill="#ffffff")
        draw.text((70, 216), "Ein Workspace für Ihre Marke.", font=cls._font(31), fill="#e0e7ff")
        x, y = 625, 65
        for n, label in enumerate(("Brand Pulse", "Content Studio", "Freigaben", "Reports")):
            top = y + n * 92
            draw.rounded_rectangle((x, top, 960, top + 70), radius=20, fill="#ffffff", outline="#dbeafe")
            draw.text((x + 26, top + 20), label, font=cls._font(23, True), fill="#1e3a8a")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    @classmethod
    def _screenshot_bytes(cls, width, height, index, title, subtitle):
        image = Image.new("RGB", (width, height), "#f5f7fb"); draw = ImageDraw.Draw(image); scale = width / 1080
        mx = int(62 * scale); blue = "#2563eb"; navy = "#0f172a"; muted = "#64748b"
        draw.rounded_rectangle((mx, int(70*scale), mx+int(70*scale), int(140*scale)), radius=int(20*scale), fill=blue)
        draw.text((mx+int(35*scale), int(102*scale)), "S", anchor="mm", font=cls._font(int(38*scale), True), fill="#fff")
        draw.text((mx+int(92*scale), int(84*scale)), "Smarbiz", font=cls._font(int(34*scale), True), fill=navy)
        y = int(190*scale)
        y = cls._draw_wrapped(draw, title, (mx, y), width-2*mx, cls._font(int(58*scale), True), navy, int(10*scale))
        y += int(22*scale)
        y = cls._draw_wrapped(draw, subtitle, (mx, y), width-2*mx, cls._font(int(26*scale)), muted, int(8*scale))
        y += int(55*scale)
        card_left, card_right = mx, width-mx
        draw.rounded_rectangle((card_left, y, card_right, height-int(190*scale)), radius=int(32*scale), fill="#ffffff", outline="#e2e8f0", width=max(2,int(2*scale)))
        cy = y + int(40*scale); cx = card_left + int(36*scale); cw = card_right-card_left-int(72*scale)
        labels = [
            [("Content-Plan", "Diese Woche · 12 Inhalte"), ("Instagram", "Produktstory · zur Freigabe"), ("LinkedIn", "B2B Insight · geplant"), ("Google Business", "Update · Entwurf")],
            [("Brand Pulse", "Ton: klar · hochwertig · direkt"), ("AI Draft", "Auf Marke und Zielgruppe abgestimmt"), ("Qualitätscheck", "92 / 100 · bereit zur Prüfung"), ("Varianten", "Kurz · Lang · LinkedIn")],
            [("Freigabe", "Reviewer eingeladen"), ("Öffentlicher Link", "Sicher geteilt"), ("Feedback", "Änderung gespeichert"), ("Status", "Freigegeben ✓")],
            [("Kampagne", "August Launch"), ("Kalender", "Woche 33 vollständig"), ("Performance", "+18% Interaktionen"), ("Nächster Schritt", "Insight in Planung übernehmen")],
        ][index]
        for n,(name,value) in enumerate(labels):
            top = cy + n*int(190*scale)
            draw.rounded_rectangle((cx,top,cx+cw,top+int(145*scale)),radius=int(24*scale),fill="#f8fafc",outline="#e2e8f0")
            draw.text((cx+int(24*scale),top+int(25*scale)),name,font=cls._font(int(22*scale),True),fill=blue)
            draw.text((cx+int(24*scale),top+int(72*scale)),value,font=cls._font(int(27*scale),True),fill=navy)
        draw.text((mx, height-int(105*scale)), "A+ Solution GmbH", font=cls._font(int(20*scale), True), fill="#94a3b8")
        stream=io.BytesIO(); image.save(stream,"PNG",optimize=True); return stream.getvalue()

    def _upsert_assets(self, app):
        self._save_asset(app, kind="icon", platform="shared", filename="smarbiz-icon-512.png", data=self._icon_bytes(), width=512, height=512)
        self._save_asset(app, kind="feature_graphic", platform="android", filename="smarbiz-feature-1024x500.png", data=self._feature_bytes(), width=1024, height=500)
        frames = [
            ("Content-Plan in Minuten", "Planen Sie Kanäle und Formate für die ganze Woche."),
            ("KI, die Ihre Marke kennt", "Brand Pulse und Regeln fließen direkt in neue Entwürfe ein."),
            ("Freigaben ohne Chat-Chaos", "Review-Link, Feedback und Entscheidung bleiben nachvollziehbar."),
            ("Kalender, Kampagnen & Reports", "Vom Plan bis zum Insight behalten Sie alles an einem Ort."),
        ]
        for index,(title,subtitle) in enumerate(frames):
            self._save_asset(app,kind="screenshot",platform="android",filename=f"android-{index+1}.png",data=self._screenshot_bytes(1080,1920,index,title,subtitle),width=1080,height=1920,sort_order=index,device_type="phone")
            self._save_asset(app,kind="screenshot",platform="ios",filename=f"ios-{index+1}.png",data=self._screenshot_bytes(1284,2778,index,title,subtitle),width=1284,height=2778,sort_order=index,device_type="APP_IPHONE_65")
        self.stdout.write("store_assets=ready")

    def _upsert_compliance(self, app):
        profile, _ = ComplianceProfile.objects.get_or_create(app=app)
        profile.primary_locale = "de-DE"
        profile.support_email = "app@aplus-solution.de"
        profile.purpose = "B2B Workspace für Markenstrategie, KI-gestützte Content-Erstellung, Planung, Freigaben und Reports."
        profile.business_model = "B2B SaaS; the mobile app contains no purchase flow"
        profile.has_ads = False
        profile.target_age_groups = ["18 and over"]
        profile.app_access = "restricted"
        profile.app_access_instructions = "Use the Publisher-managed App Review account. No purchase is required. Account deletion is available from Settings → Account deletion."
        profile.account_deletion = "in_app"
        profile.account_deletion_url = f"{PUBLIC_URL}/de/account-deletion"
        profile.payment_handling = "none"
        profile.payment_details = "No purchases, prices, subscriptions or external payment links are presented in mobile version 1.0."
        profile.data_practices = {
            "encrypted_in_transit": True,
            "deletion_request": True,
            "account_creation": True,
            "data_types": {
                "personal_info.email": {"label": "Email address", "collected": True, "shared": False, "required": True, "purposes": ["account_management", "app_functionality"]},
                "personal_info.name": {"label": "Name", "collected": True, "shared": False, "required": False, "purposes": ["account_management"]},
                "user_ids": {"label": "User IDs", "collected": True, "shared": False, "required": True, "purposes": ["account_management", "app_functionality"]},
                "user_content.other": {"label": "Workspace and content data", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "diagnostics.other": {"label": "Security and diagnostics", "collected": True, "shared": False, "required": False, "purposes": ["fraud_prevention", "app_functionality"]},
            },
        }
        profile.content_rating_answers = {"violence":False,"sexual_content":False,"language":False,"controlled_substances":False,"gambling":False,"user_generated_content":False,"location_sharing":False}
        profile.store_declarations = {"contains_ads":False,"target_age_groups":["18 and over"],"designed_for_children":False,"app_access":"restricted","privacy_policy_url":f"{PUBLIC_URL}/de/privacy","account_deletion_url":f"{PUBLIC_URL}/de/account-deletion"}
        profile.unresolved_questions = [
            "Google Play: the first app record must exist in Play Console before Android Publisher API upload can start.",
            "Google Play: verify Data Safety and content-rating console declarations before production rollout.",
            "Apple: the first App Store Connect app record must exist before Publisher can attach/upload the build.",
            "Apple: verify App Privacy answers in App Store Connect before submission.",
        ]
        profile.console_autofill = _console_autofill(profile)
        profile.status = "needs_review"; profile.confidence = 0.96; profile.save()
        self.stdout.write("compliance_profile=ready")

    def _upsert_release(self, app, version, build_number):
        release, _ = Release.objects.update_or_create(
            app=app, version_name=version, build_number=build_number,
            defaults={"source_branch":"main","android_track":"production","android_rollout":1,"ios_release_type":"manual","auto_submit":False,"release_notes":"Erste mobile Version von Smarbiz mit Brand Pulse, Content Studio, Freigaben, Kalender und Reports."},
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
        body = {"data":{"type":"bundleIds","attributes":{"identifier":APP_ID,"name":"Smarbiz","platform":"IOS"}}}
        item = client.request("POST", "/bundleIds", data=json.dumps(body))["data"]
        self.stdout.write(self.style.SUCCESS("apple_bundle_id=registered"))
        return item
