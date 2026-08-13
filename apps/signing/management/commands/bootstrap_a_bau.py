from __future__ import annotations

import io
import json
import os
import textwrap
from pathlib import Path

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from PIL import Image, ImageDraw, ImageFont

from apps.compliance.models import ComplianceProfile
from apps.compliance.services import _console_autofill
from apps.integrations.apple_store import AppleStoreClient
from apps.integrations.google_play import GooglePlayClient
from apps.publisher.job_recovery import recover_stale_internal_jobs
from apps.publisher.models import AppAsset, AppLocalization, Build, Job, MobileApp, Release, StoreAccount
from apps.publisher.tasks import enqueue_job
from apps.signing.services import ensure_android_signing, ensure_ios_signing


APP_SLUG = "a-bau"
APP_ID = "de.kayihaustechnik.app"
APP_REPO = "https://github.com/hsdarestani/KAYIHAUSTECHNIK"
PUBLIC_URL = "https://kayi.smarbiz.sbs"
ICON_URL = "https://raw.githubusercontent.com/hsdarestani/KAYIHAUSTECHNIK/main/branding/fav.png"


class Command(BaseCommand):
    help = "Create/update A+Bau in Publisher, prepare signing/store assets, build and submit to Apple/Google."

    def add_arguments(self, parser):
        parser.add_argument("--app-version", default="2.2.0")
        parser.add_argument("--build-number", type=int, default=22001)
        parser.add_argument("--queue", action="store_true")
        parser.add_argument("--publish", action="store_true")
        parser.add_argument("--diagnose-only", action="store_true")

    def handle(self, *args, **options):
        if options["build_number"] < 1:
            raise CommandError("--build-number must be >= 1")

        app = self._find_app()
        if options["diagnose_only"]:
            if not app:
                raise CommandError("A+Bau is not registered in Publisher yet.")
            release = Release.objects.filter(
                app=app,
                version_name=options["app_version"],
                build_number=options["build_number"],
            ).first()
            self._report(app, release)
            return

        with transaction.atomic():
            app = self._upsert_app(app)
            self._upsert_localization(app)
            self._upsert_assets(app)
            self._upsert_compliance(app)
            release = self._upsert_release(app, options["app_version"], options["build_number"])

        self._recover_stale(app, release)
        self._prepare_signing(app)
        if options["queue"]:
            self._queue_builds(app, release)
        if options["publish"]:
            self._advance_publication(app, release)
        self._report(app, release)

    def _find_app(self):
        return (
            MobileApp.objects.filter(slug=APP_SLUG).first()
            or MobileApp.objects.filter(Q(package_name=APP_ID) | Q(bundle_id=APP_ID)).order_by("-updated_at").first()
        )

    def _configured_account(self, provider: str, app=None):
        linked = getattr(app, f"{provider}_account", None) if app else None
        if linked and linked.enabled and linked.configured:
            return linked
        return next(
            (
                account
                for account in StoreAccount.objects.filter(provider=provider, enabled=True).order_by("created_at")
                if account.configured
            ),
            None,
        )

    def _upsert_app(self, app):
        legacy = MobileApp.objects.filter(Q(package_name=APP_ID) | Q(bundle_id=APP_ID)).order_by("-updated_at").first()
        app = app or legacy or MobileApp(slug=APP_SLUG)

        # Preserve any prior review credentials, store IDs and encrypted repository token
        # by updating the same package/bundle record instead of creating a duplicate app.
        google_account = self._configured_account("google", app or legacy)
        apple_account = self._configured_account("apple", app or legacy)

        app.name = "A+Bau"
        app.slug = APP_SLUG
        app.client_name = "A+ Solution GmbH"
        app.platform = "both"
        app.framework = "other"
        app.status = "active"
        app.package_name = APP_ID
        app.bundle_id = APP_ID
        app.repository_url = APP_REPO
        app.default_branch = "main"
        app.privacy_policy_url = f"{PUBLIC_URL}/datenschutz/"
        app.support_url = f"{PUBLIC_URL}/support/"
        app.marketing_url = f"{PUBLIC_URL}/"
        app.category = "Business"
        app.content_rating = "4+"
        app.requires_login = True
        app.google_account = google_account
        app.apple_account = apple_account
        app.build_config = {
            "android_command": "bash scripts/publisher-build-android.sh",
            "android_artifact": "native/android/app/build/outputs/bundle/release/*.aab",
            "ios_command": "bash scripts/publisher-build-ios.sh",
            "ios_artifact": "artifacts/a-bau.ipa",
        }
        app.tech_stack = ["Django", "Capacitor", "JavaScript", "Android", "iOS", "ARCore", "RoomPlan"]
        app.review_notes = (
            "A+Bau ist eine B2B-App für Handwerks- und Baubetriebe. Die App benötigt einen betrieblichen Zugang. "
            "Bitte die im App Review / App Access Feld hinterlegten Demo-Zugangsdaten verwenden. Das Demo-Konto enthält "
            "Beispielkunden, Projekte, Termine und Dokumente. Kamera und Mikrofon werden nur nach einer aktiven Aktion angefragt. "
            "Optionale KI-Funktionen benötigen eine separate Einwilligung. Rollenrechte begrenzen Datenzugriff und interne Preis-/Finanzdaten. "
            f"Kontolöschung: {PUBLIC_URL}/konto-loeschen/ · Datenschutz: {PUBLIC_URL}/datenschutz/ · Support: {PUBLIC_URL}/support/."
        )

        env_user = os.getenv("A_BAU_REVIEW_USERNAME", "").strip()
        env_password = os.getenv("A_BAU_REVIEW_PASSWORD", "").strip()
        if env_user:
            app.review_username = env_user
        if env_password:
            app.set_review_password(env_password)

        app.save()
        self.stdout.write("app=updated" if app.pk else "app=created")
        self.stdout.write(f"app_id={app.pk}")
        self.stdout.write(f"review_credentials={'ready' if app.review_username and app.get_review_password() else 'missing'}")
        self.stdout.write(f"google_account={'configured' if google_account else 'missing'}")
        self.stdout.write(f"apple_account={'configured' if apple_account else 'missing'}")
        return app

    def _upsert_localization(self, app):
        full = (
            "A+Bau verbindet Büro und Baustelle in einem klaren digitalen Arbeitsablauf.\n\n"
            "Kunden und Projekte verwalten, Termine planen, Arbeitszeiten erfassen und Einsätze direkt vor Ort dokumentieren. "
            "Fotos, Aufmaße, Arbeitsberichte und Kundenunterschriften bleiben dem passenden Auftrag zugeordnet.\n\n"
            "Monteure erfassen neue Arbeiten ohne interne Preis- oder Margendaten. Das Büro prüft und kalkuliert die Positionen, "
            "bevor der Kunde den finalen Preis sieht und unterschreibt.\n\n"
            "Für das Büro umfasst A+Bau Angebote, Rechnungen, Zahlungen, Finanzen, Ausgaben, Aufgaben, Mitarbeiter und Dokumente. "
            "Auf unterstützten Geräten stehen Raumscan, Fotoanalyse und bearbeitbare 3D-Raummodelle zur Verfügung.\n\n"
            "Optionale KI-Funktionen arbeiten innerhalb derselben Rollen- und Projektberechtigungen wie die App. Eine Übertragung "
            "nutzerbezogener Inhalte an den KI-Dienst erfolgt erst nach ausdrücklicher Einwilligung und kann jederzeit widerrufen werden.\n\n"
            "A+Bau ist für professionelle Handwerks- und Baubetriebe vorgesehen. Zur Nutzung ist ein betrieblicher Zugang erforderlich."
        )
        AppLocalization.objects.update_or_create(
            app=app,
            locale="de-DE",
            defaults={
                "title": "A+Bau",
                "subtitle": "Baustelle. Büro. Im Griff.",
                "short_description": "Aufträge, Termine, Zeiterfassung, Baustellendoku, Aufmaß und Finanzen in einer App.",
                "full_description": full,
                "keywords": "Handwerk,Bau,Auftrag,Zeiterfassung,Aufmaß,Baustelle,Rechnung,Termin,Projekt",
                "promotional_text": "Von der Baustelle bis zur Rechnung: A+Bau verbindet Einsätze, Freigaben, Aufmaß, Finanzen und Büroarbeit in einem Ablauf.",
                "release_notes": (
                    "Neues A+Bau Branding und App-Icon. Verbesserte Angebote, Rechnungen und Finanzen. Neuer Monteur-zu-Büro-"
                    "Freigabeablauf, erweiterte Einsatzprüfung, bessere Zeiterfassung, Projektteam-Auswahl und rollenbasierte KI-Berechtigungen."
                ),
            },
        )
        self.stdout.write("localization=ready")

    @staticmethod
    def _font(size: int, bold=False):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _icon_bytes(self, size=512):
        response = requests.get(ICON_URL, timeout=30)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as source:
            source = source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            image = Image.new("RGBA", (size, size), "#0d0e10")
            image.alpha_composite(source)
        stream = io.BytesIO()
        image.convert("RGB").save(stream, "PNG", optimize=True)
        return stream.getvalue()

    @classmethod
    def _feature_bytes(cls):
        w, h = 1024, 500
        image = Image.new("RGB", (w, h), "#0d0e10")
        draw = ImageDraw.Draw(image)
        draw.ellipse((690, -200, 1160, 270), fill="#2b2518")
        draw.text((70, 76), "A+Bau", font=cls._font(60, True), fill="#f2eee4")
        draw.text((70, 170), "Alles organisiert. Alles im Griff.", font=cls._font(34, True), fill="#d7b454")
        draw.text((70, 238), "Von der Baustelle bis zur Rechnung.", font=cls._font(27), fill="#c9c4b8")
        draw.text((70, 340), "Aufträge  ·  Doku  ·  Aufmaß  ·  Freigaben  ·  Finanzen", font=cls._font(20), fill="#f2eee4")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    @classmethod
    def _screenshot_bytes(cls, width, height, index, title, subtitle):
        image = Image.new("RGB", (width, height), "#f4f2ed")
        draw = ImageDraw.Draw(image)
        scale = width / 1080
        mx = int(64 * scale)
        gold = "#c9a13b"; dark = "#111315"; muted = "#686a6e"; panel = "#ffffff"; line = "#dedbd3"
        draw.rectangle((0, 0, width, int(118 * scale)), fill=dark)
        draw.text((mx, int(32 * scale)), "A+Bau", font=cls._font(int(38 * scale), True), fill="#f4f2ed")
        draw.text((width-int(250*scale), int(44*scale)), "A+ KI", font=cls._font(int(20*scale), True), fill=gold)
        y = int(175 * scale)
        draw.text((mx, y), title, font=cls._font(int(48 * scale), True), fill=dark)
        y += int(72 * scale)
        draw.text((mx, y), subtitle, font=cls._font(int(24 * scale)), fill=muted)
        y += int(70 * scale)
        card = (mx, y, width-mx, min(height-int(120*scale), y+int(1120*scale)))
        draw.rounded_rectangle(card, radius=int(30*scale), fill=panel, outline=line, width=max(2,int(2*scale)))
        cx = card[0]+int(34*scale); cy = card[1]+int(40*scale); cw = card[2]-card[0]-int(68*scale)
        headings = ["Projekte & Termine", "Einsatz vor Ort", "Freigabe & Kalkulation", "Finanzen & KI"]
        draw.text((cx, cy), headings[index], font=cls._font(int(27*scale), True), fill=dark)
        if index == 0:
            rows = [("Sanierung Bad · Frankfurt", "Heute · 09:00", "In Arbeit"), ("Heizung · Offenbach", "Morgen · 08:30", "Geplant"), ("Küche · Hanau", "Fr · 10:00", "Freigabe")]
        elif index == 1:
            rows = [("Arbeitsbericht", "Sprachnotiz & Text", "Bereit"), ("Vorher / Nachher", "6 Fotos", "Dokumentiert"), ("Zeiterfassung", "02:47 h", "Läuft")]
        elif index == 2:
            rows = [("Monteur-Aufnahme", "ohne Preisdaten", "Eingereicht"), ("Büro-Prüfung", "Positionen & Marge", "Geprüft"), ("Kundenfreigabe", "Finalpreis & Signatur", "Bereit")]
        else:
            rows = [("Angebote & Rechnungen", "B&O / VA04 Preise", "Aktuell"), ("Projektmarge", "EK · VK · Aufschlag", "Büro"), ("A+ KI", "rollenbasiert & scoped", "Geschützt")]
        top = cy + int(90*scale)
        for n, (name, detail, status) in enumerate(rows):
            box_top = top + n*int(235*scale)
            draw.rounded_rectangle((cx, box_top, cx+cw, box_top+int(190*scale)), radius=int(22*scale), fill="#faf9f6", outline=line)
            draw.rectangle((cx, box_top, cx+int(8*scale), box_top+int(190*scale)), fill=gold)
            draw.text((cx+int(30*scale), box_top+int(30*scale)), name, font=cls._font(int(27*scale), True), fill=dark)
            draw.text((cx+int(30*scale), box_top+int(82*scale)), detail, font=cls._font(int(21*scale)), fill=muted)
            draw.text((cx+int(30*scale), box_top+int(132*scale)), status, font=cls._font(int(18*scale), True), fill="#8a6820")
        draw.text((mx, height-int(70*scale)), "Alles organisiert. Alles im Griff.", font=cls._font(int(18*scale), True), fill="#77756f")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    def _save_asset(self, app, *, kind, platform, filename, data, width, height, sort_order=0, device_type=""):
        asset = AppAsset.objects.filter(
            app=app, kind=kind, platform=platform, locale="de-DE", device_type=device_type, sort_order=sort_order
        ).first()
        if not asset:
            asset = AppAsset(
                app=app, kind=kind, platform=platform, locale="de-DE", device_type=device_type,
                sort_order=sort_order, width=width, height=height,
            )
        else:
            asset.width = width; asset.height = height; asset.checksum = ""
        asset.file.save(filename, ContentFile(data), save=True)
        return asset

    def _upsert_assets(self, app):
        self._save_asset(app, kind="icon", platform="shared", filename="a-bau-fav-512.png", data=self._icon_bytes(), width=512, height=512)
        self._save_asset(app, kind="feature_graphic", platform="android", filename="a-bau-feature-1024x500.png", data=self._feature_bytes(), width=1024, height=500)
        frames = [
            ("Alles an einem Ort.", "Projekte, Kunden und Termine übersichtlich verwalten."),
            ("Direkt auf der Baustelle.", "Zeit, Fotos, Berichte und Aufmaß im Einsatz dokumentieren."),
            ("Erst prüfen. Dann freigeben.", "Monteur, Büro und Kunde in einem nachvollziehbaren Ablauf."),
            ("Von der Kalkulation zur Rechnung.", "Preise, Margen, Finanzen und KI nur für berechtigte Rollen."),
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
        self.stdout.write("store_assets=ready source=branding/fav.png")

    def _upsert_compliance(self, app):
        profile, _ = ComplianceProfile.objects.get_or_create(app=app)
        profile.primary_locale = "de-DE"
        profile.support_email = "app@aplus-solution.de"
        profile.purpose = "B2B-Auftrags-, Baustellen-, Dokumentations-, Aufmaß-, Freigabe- und Finanzworkflow für Handwerksbetriebe."
        profile.business_model = "B2B business software; no in-app purchases or advertising"
        profile.has_ads = False
        profile.target_age_groups = ["18 and over"]
        profile.app_access = "restricted"
        profile.app_access_instructions = "Mit den im Store Review/App Access Bereich hinterlegten A+Bau Demo-Zugangsdaten anmelden. Kein OTP und kein Kauf erforderlich."
        profile.account_deletion = "in_app"
        profile.account_deletion_url = f"{PUBLIC_URL}/konto-loeschen/"
        profile.payment_handling = "none"
        profile.payment_details = "A+Bau verkauft keine digitalen Güter und enthält keine In-App-Käufe."
        profile.data_practices = {
            "encrypted_in_transit": True,
            "deletion_request": True,
            "account_creation": False,
            "data_types": {
                "personal_info.name": {"label": "Name", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "personal_info.email": {"label": "Email address", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality", "account_management"]},
                "personal_info.phone": {"label": "Phone number", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "personal_info.address": {"label": "Physical address", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "user_content.photos": {"label": "Photos or videos", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "user_content.audio": {"label": "Audio data", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "user_content.other": {"label": "Other user-generated content", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "financial_info.other": {"label": "Other financial info", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
                "user_ids": {"label": "User IDs", "collected": True, "shared": False, "required": True, "purposes": ["account_management", "app_functionality"]},
                "app_activity.interactions": {"label": "Product interaction", "collected": True, "shared": False, "required": False, "purposes": ["app_functionality"]},
            },
        }
        profile.content_rating_answers = {
            "violence": False, "sexual_content": False, "language": False,
            "controlled_substances": False, "gambling": False,
            "user_generated_content": False, "location_sharing": False,
        }
        profile.store_declarations = {
            "contains_ads": False,
            "target_age_groups": ["18 and over"],
            "designed_for_children": False,
            "app_access": "restricted",
            "privacy_policy_url": f"{PUBLIC_URL}/datenschutz/",
            "account_deletion_url": f"{PUBLIC_URL}/konto-loeschen/",
        }
        profile.unresolved_questions = []
        if not app.review_username or not app.get_review_password():
            profile.unresolved_questions.append("Store review demo credentials are still missing in Publisher.")
        profile.console_autofill = _console_autofill(profile)
        profile.status = "needs_review" if profile.unresolved_questions else "ready"
        profile.confidence = 0.97
        profile.save()
        self.stdout.write(f"compliance_profile={profile.status}")

    def _upsert_release(self, app, version, build_number):
        release, _ = Release.objects.update_or_create(
            app=app, version_name=version, build_number=build_number,
            defaults={
                "source_branch": "main",
                "android_track": "production",
                "android_rollout": 1,
                "ios_release_type": "manual",
                "auto_submit": True,
                "release_notes": "A+Bau Branding, neues fav.png App-Icon, neue Freigaben, Finanzen, Zeiterfassung und rollenbasierte KI-Berechtigungen.",
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
        body = {"data": {"type": "bundleIds", "attributes": {"identifier": APP_ID, "name": "A+Bau", "platform": "IOS"}}}
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
            self.stdout.write(self.style.WARNING("ios_signing=blocked apple_account_missing")); return
        try:
            self._ensure_apple_bundle_id(app)
            profile = ensure_ios_signing(app)
            self.stdout.write(self.style.SUCCESS(f"ios_signing=ready profile={profile.profile_name}"))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"ios_signing=blocked {exc}"))

    def _recover_stale(self, app, release):
        recovered = recover_stale_internal_jobs(app=app, release=release, stale_after_minutes=10)
        self.stdout.write("recovered_stale_jobs=" + (",".join(map(str, recovered)) if recovered else "none"))

    def _queue_one(self, app, release, platform):
        build, _ = Build.objects.get_or_create(release=release, platform=platform)
        if build.status == "succeeded" and build.artifact:
            self.stdout.write(f"{platform}_build=already_succeeded"); return
        job_type = "build_android" if platform == "android" else "build_ios"
        required = "linux" if platform == "android" else "macos"
        if Job.objects.filter(app=app, release=release, build=build, type=job_type, status__in=["queued", "running"]).exists():
            self.stdout.write(f"{platform}_build=already_queued"); return
        build.status = "queued"; build.logs = ""; build.save(update_fields=["status", "logs", "updated_at"])
        release.status = "building"; release.save(update_fields=["status", "updated_at"])
        Job.objects.create(
            type=job_type, app=app, release=release, build=build,
            payload={"source": "a-bau-bootstrap"}, available_to_agents=True, required_platform=required,
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
        return Job.objects.filter(app=app, release=release, build=build, type=job_type, status__in=["queued", "running", "succeeded"]).exists()

    def _advance_publication(self, app, release):
        records = self._store_records(app)
        android = release.builds.filter(platform="android", status="succeeded").first()
        if android and records["google"]["ready"]:
            if not self._job_exists(app, release, android, "upload_google"):
                enqueue_job("upload_google", app=app, release=release, build=android)
                self.stdout.write(self.style.SUCCESS("google_publish=queued"))
            else:
                self.stdout.write("google_publish=already_queued_or_done")
        elif android:
            self.stdout.write(self.style.WARNING("google_publish=blocked store_record_or_api_access"))

        ios = release.builds.filter(platform="ios", status="succeeded").first()
        if ios and records["apple"]["ready"]:
            if not ios.external_build_id:
                if not self._job_exists(app, release, ios, "upload_apple"):
                    Job.objects.create(
                        type="upload_apple", app=app, release=release, build=ios,
                        payload={"source": "a-bau-bootstrap"}, available_to_agents=True, required_platform="macos",
                    )
                    self.stdout.write(self.style.SUCCESS("apple_upload=queued"))
                else:
                    self.stdout.write("apple_upload=already_queued_or_done")
            elif not self._job_exists(app, release, ios, "submit_apple"):
                enqueue_job("submit_apple", app=app, release=release, build=ios)
                self.stdout.write(self.style.SUCCESS("apple_submit=queued"))
            else:
                self.stdout.write("apple_submit=already_queued_or_done")
        elif ios:
            self.stdout.write(self.style.WARNING("apple_publish=blocked app_store_connect_record_missing"))

    def _report(self, app, release):
        records = self._store_records(app)
        self.stdout.write("--- a-bau-status ---")
        self.stdout.write(f"app_id={app.pk} package={app.package_name} bundle={app.bundle_id}")
        self.stdout.write(f"review_credentials={'ready' if app.review_username and app.get_review_password() else 'missing'}")
        self.stdout.write(f"google_record={'ready' if records['google']['ready'] else 'blocked'}")
        self.stdout.write(textwrap.shorten(f"google_detail={records['google']['message']}", width=900, placeholder="..."))
        self.stdout.write(f"apple_record={'ready' if records['apple']['ready'] else 'blocked'}")
        self.stdout.write(textwrap.shorten(f"apple_detail={records['apple']['message']}", width=900, placeholder="..."))
        if release:
            self.stdout.write(f"release={release.version_name}({release.build_number}) status={release.status}")
            for build in release.builds.order_by("platform"):
                self.stdout.write(f"build_{build.platform}={build.status} artifact={'yes' if build.artifact else 'no'} external_id={build.external_build_id or '-'}")
            for job in release.jobs.order_by("created_at"):
                self.stdout.write(f"job={job.type}:{job.status} error={textwrap.shorten(job.error or '-', width=500, placeholder='...')}")
