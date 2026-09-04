from __future__ import annotations

import io

from django.utils import timezone
from PIL import Image, ImageDraw

from apps.compliance.services import _console_autofill
from apps.publisher.models import AppAsset, Release
from apps.signing.management.commands import bootstrap_a_studio as base

ASTUDIO_COMMIT = "d435b5c066120045cb0f61cfc0f79a20298ffbcc"
BUILD_NUMBER = 10


class Command(base.Command):
    help = "Prepare A+ Studio Build 10 as the real Cloud App Builder with a strict iOS execution boundary."

    def handle(self, *args, **options):
        # Reuse the proven signing/build/upload/submission machinery, but point it
        # at the real Cloud App Builder source and never allow Build 9 fallback.
        base.ASTUDIO_COMMIT = ASTUDIO_COMMIT
        base.CURRENT_BUILD_NUMBER = BUILD_NUMBER
        options["build_number"] = max(int(options.get("build_number") or BUILD_NUMBER), BUILD_NUMBER)
        return super().handle(*args, **options)

    def _upsert_app(self):
        app = super()._upsert_app()
        app.requires_login = False
        app.review_username = ""
        app.review_password_blob = ""
        app.review_notes = (
            "Guideline 2.5.2 clarification for Build 10. A+ Studio is genuinely a cloud app builder, and this build "
            "preserves that core product function while enforcing a strict iOS execution boundary. Existing users can "
            "create a new app project in the iOS client by submitting ordinary project requirements (name, business type, "
            "description and language). Generation and build processing occur only on A+ Studio cloud infrastructure. "
            "The iOS client receives project metadata, textual cloud lifecycle status and change-request status only. "
            "Generated source code, repositories, IPA/APK files, deployment artifacts, preview URLs and live URLs are not "
            "returned by the mobile API. The iOS client does not download, install, execute, embed, iframe, WebView, launch "
            "or otherwise run generated application code, and it exposes no mobile publishing or App Store / Play Store "
            "submission controls. Tap 'Demo ansehen' on the sign-in screen to review the complete iOS workflow without an "
            "account. The production endpoint /api/mobile/config/ also exposes this capability contract explicitly."
        )
        app.save(update_fields=[
            "requires_login", "review_username", "review_password_blob", "review_notes", "updated_at"
        ])
        return app

    @staticmethod
    def _de_metadata():
        return {
            "title": "A+ Studio",
            "subtitle": "Cloud App Builder",
            "short_description": "Apps als Cloud-Projekte erstellen",
            "full_description": (
                "A+ Studio ist ein Cloud App Builder für bestehende A+ Studio Nutzer. Starten Sie neue App-Projekte direkt "
                "auf dem iPhone, beschreiben Sie Ziel und Funktionen und verfolgen Sie die serverseitige Erstellung.\n\n"
                "In der iOS-App können Sie App-Projekte anlegen, den Cloud-Status verfolgen und Änderungswünsche verwalten. "
                "Generierung und Build-Verarbeitung erfolgen auf der A+ Studio Cloud-Infrastruktur.\n\n"
                "Die erzeugte Anwendung wird innerhalb der iOS-App nicht heruntergeladen, installiert oder ausgeführt. "
                "Die iOS-App zeigt keine ausführbare Vorschau einer erzeugten App und enthält keine mobilen Build-Download-, "
                "Publishing- oder Store-Submission-Funktionen. Konten werden außerhalb der iOS-App eingerichtet. "
                "Ein Demo-Modus auf der Anmeldeseite zeigt den vollständigen mobilen Ablauf ohne Konto."
            ),
            "keywords": "appbuilder,cloud,projekt,entwicklung,workflow,software",
            "promotional_text": "Neue App-Projekte mobil starten und ihre Erstellung in der A+ Studio Cloud verfolgen.",
            "release_notes": "Cloud App Builder wieder vollständig verfügbar: neue App-Projekte starten, Cloud-Status verfolgen und Änderungen verwalten – mit klarer iOS-Ausführungsgrenze.",
        }

    @staticmethod
    def _en_metadata():
        return {
            "title": "A+ Studio",
            "subtitle": "Cloud App Builder",
            "short_description": "Create apps as cloud projects",
            "full_description": (
                "A+ Studio is a cloud app builder for existing A+ Studio users. Start new app projects from your iPhone, "
                "describe the product and required features, and follow server-side creation.\n\n"
                "The iOS app lets you create app projects, follow cloud status and manage change requests. Generation and "
                "build processing take place on A+ Studio cloud infrastructure.\n\n"
                "The generated application is not downloaded, installed or executed inside the iOS app. The iOS app does "
                "not provide an executable preview of generated apps and contains no mobile build-download, publishing or "
                "store-submission controls. Accounts are provisioned outside the iOS app. A demo mode on the sign-in screen "
                "shows the complete mobile workflow without an account."
            ),
            "keywords": "appbuilder,cloud,project,development,workflow,software",
            "promotional_text": "Start new app projects on mobile and follow their creation in A+ Studio Cloud.",
            "release_notes": "The Cloud App Builder is fully available again: start projects, follow cloud status and manage changes with a strict iOS execution boundary.",
        }

    @classmethod
    def _feature_bytes(cls):
        image = Image.new("RGB", (1024, 500), "#0b0c0f")
        draw = ImageDraw.Draw(image)
        draw.ellipse((650, -180, 1120, 290), fill="#292319")
        draw.text((70, 72), "A+ STUDIO", font=cls._font(30, True), fill="#e7c66d")
        draw.text((70, 140), "Cloud App Builder", font=cls._font(58, True), fill="#f4f2ea")
        draw.text((72, 235), "Idee  •  Cloud-Erstellung  •  Änderungen", font=cls._font(25), fill="#a6abb4")
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
        card = (mx, y, width-mx, min(height-int(220*scale), y+int(980*scale)))
        draw.rounded_rectangle(card, radius=int(34*scale), fill="#17191e", outline="#30333a", width=max(2, int(2*scale)))
        cx, cy, cw = card[0]+int(34*scale), card[1]+int(38*scale), card[2]-card[0]-int(68*scale)

        if index == 0:
            draw.text((cx, cy), "NEW APP PROJECT" if english else "NEUES APP-PROJEKT", font=cls._font(int(20*scale), True), fill="#e7c66d")
            fields = [
                ("App name" if english else "App-Name", "Luna Booking"),
                ("Business type" if english else "Branche", "Salon"),
                ("Goal & features" if english else "Ziel & Funktionen", "Booking, availability, customer flow" if english else "Buchung, Verfügbarkeit, Kundenablauf"),
            ]
            top = cy + int(95*scale)
            for label, value in fields:
                draw.text((cx, top), label, font=cls._font(int(20*scale), True), fill="#9298a2")
                h = int(120*scale)
                draw.rounded_rectangle((cx, top+int(38*scale), cx+cw, top+h), radius=int(18*scale), fill="#101216", outline="#30333a")
                cls._draw_wrapped(draw, value, (cx+int(22*scale), top+int(60*scale)), cw-int(44*scale), cls._font(int(23*scale)), "#f5f4f0", int(8*scale))
                top += int(155*scale)
            draw.rounded_rectangle((cx, top+int(15*scale), cx+cw, top+int(115*scale)), radius=int(22*scale), fill="#d9ba64")
            draw.text((cx+int(28*scale), top+int(45*scale)), "Start cloud creation" if english else "Cloud-Erstellung starten", font=cls._font(int(23*scale), True), fill="#17130b")
        elif index == 1:
            draw.text((cx, cy), "CLOUD STATUS", font=cls._font(int(20*scale), True), fill="#e7c66d")
            rows = [
                ("Project created" if english else "Projekt angelegt", "Done" if english else "Erledigt"),
                ("Cloud generation" if english else "Cloud-Generierung", "Running" if english else "Läuft"),
                ("Generated" if english else "Erstellt", "Pending" if english else "Ausstehend"),
            ]
            for n, (key, value) in enumerate(rows):
                top = cy + int((115+n*175)*scale)
                draw.line((cx, top, cx+cw, top), fill="#2d3036", width=max(1, int(scale)))
                draw.text((cx, top+int(35*scale)), key, font=cls._font(int(23*scale)), fill="#9298a2")
                draw.text((cx+int(380*scale), top+int(32*scale)), value, font=cls._font(int(23*scale), True), fill="#f5f4f0")
        elif index == 2:
            draw.text((cx, cy), "CHANGE REQUEST" if english else "ÄNDERUNGSWUNSCH", font=cls._font(int(20*scale), True), fill="#e7c66d")
            text = "Add a clearer weekly booking flow and simplify the confirmation screen." if english else "Den wöchentlichen Buchungsablauf klarer machen und die Bestätigungsseite vereinfachen."
            draw.rounded_rectangle((cx, cy+int(95*scale), cx+cw, cy+int(420*scale)), radius=int(24*scale), fill="#101216", outline="#30333a")
            cls._draw_wrapped(draw, text, (cx+int(26*scale), cy+int(130*scale)), cw-int(52*scale), cls._font(int(24*scale)), "#f5f4f0", int(10*scale))
            draw.rounded_rectangle((cx, cy+int(470*scale), cx+cw, cy+int(570*scale)), radius=int(22*scale), fill="#d9ba64")
            draw.text((cx+int(28*scale), cy+int(500*scale)), "Send request" if english else "Änderungswunsch senden", font=cls._font(int(23*scale), True), fill="#17130b")
        else:
            draw.text((cx, cy), "CLOUD BOUNDARY", font=cls._font(int(20*scale), True), fill="#e7c66d")
            labels = [
                "Generation runs in A+ Studio Cloud" if english else "Generierung läuft in der A+ Studio Cloud",
                "Project status stays visible" if english else "Projektstatus bleibt mobil sichtbar",
                "No generated code runs inside iOS" if english else "Kein erzeugter Code läuft innerhalb von iOS",
                "No install or store submission from iOS" if english else "Keine Installation oder Store-Einreichung aus iOS",
            ]
            for n, label in enumerate(labels):
                top = cy + int((105+n*150)*scale)
                draw.ellipse((cx, top, cx+int(52*scale), top+int(52*scale)), fill="#294536")
                draw.text((cx+int(14*scale), top+int(5*scale)), "✓", font=cls._font(int(30*scale), True), fill="#72d8a0")
                cls._draw_wrapped(draw, label, (cx+int(82*scale), top+int(5*scale)), cw-int(82*scale), cls._font(int(23*scale), True), "#f5f4f0", int(7*scale))

        draw.text((mx, height-int(105*scale)), "A+ Solution GmbH", font=cls._font(int(20*scale), True), fill="#777d87")
        stream = io.BytesIO(); image.save(stream, "PNG", optimize=True); return stream.getvalue()

    def _upsert_assets(self, app):
        self._save_asset(app, kind="icon", platform="shared", locale="de-DE", filename="a-studio-icon-512.png", data=self._icon_bytes(), width=512, height=512)
        self._save_asset(app, kind="feature_graphic", platform="android", locale="de-DE", filename="a-studio-builder-feature-1024x500.png", data=self._feature_bytes(), width=1024, height=500)
        AppAsset.objects.filter(app=app, kind="screenshot", platform__in=["ios", "android"]).delete()
        de_frames = [
            ("Neue App-Projekte starten.", "Idee und Funktionen eingeben und die Erstellung in der Cloud starten."),
            ("Cloud-Erstellung verfolgen.", "Klarer Status, ohne erzeugten Code innerhalb der iOS-App auszuführen."),
            ("Änderungen direkt anstoßen.", "Anpassungen als Projektanforderung an die Cloud senden."),
            ("Builder-Funktion, klare Grenze.", "Erstellen in der Cloud; kein Download, Installieren oder Ausführen generierter Apps in iOS."),
        ]
        en_frames = [
            ("Start new app projects.", "Describe the idea and features and start creation in the cloud."),
            ("Follow cloud creation.", "Clear status without executing generated application code inside iOS."),
            ("Request changes directly.", "Send product changes back to the cloud workflow."),
            ("Real builder, strict boundary.", "Create in the cloud; no generated-app download, installation or execution in iOS."),
        ]
        for loc in app.localizations.all():
            english = not loc.locale.lower().startswith("de")
            frames = en_frames if english else de_frames
            for index, (title, subtitle) in enumerate(frames):
                self._save_asset(app, kind="screenshot", platform="ios", locale=loc.locale, filename=f"ios-builder-{loc.locale}-{index+1}.png", data=self._screenshot_bytes(1284, 2778, index, title, subtitle, english), width=1284, height=2778, sort_order=index, device_type="APP_IPHONE_65")
                self._save_asset(app, kind="screenshot", platform="android", locale=loc.locale, filename=f"android-builder-{loc.locale}-{index+1}.png", data=self._screenshot_bytes(1080, 1920, index, title, subtitle, english), width=1080, height=1920, sort_order=index, device_type="phone")
        self.stdout.write("store_assets=cloud_builder_no_runtime")

    def _upsert_compliance(self, app):
        super()._upsert_compliance(app)
        profile = app.compliance_profile
        profile.purpose = "Cloud-basierter App Builder: neue App-Projekte anlegen, serverseitige Erstellung verfolgen und Änderungswünsche verwalten."
        profile.business_model = "B2B cloud app creation service; no mobile purchase flow and no generated-app runtime in iOS"
        profile.app_access = "restricted"
        profile.app_access_instructions = "App Review kann über 'Demo ansehen' ohne Konto den vollständigen iOS-Builder-Ablauf prüfen. Die Demo führt keinen generierten Code aus."
        profile.payment_handling = "none"
        profile.payment_details = "Die iOS-App enthält keine Käufe, Abonnements oder externen Zahlungslinks."
        profile.store_declarations = dict(profile.store_declarations or {})
        profile.store_declarations.update({
            "app_access": "restricted",
            "cloud_app_builder": True,
            "generated_code_executes_in_ios": False,
            "generated_app_preview_in_ios": False,
            "mobile_store_submission": False,
        })
        profile.console_autofill = _console_autofill(profile)
        profile.save()
        self.stdout.write("compliance_profile=cloud_builder_no_runtime")

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
                "release_notes": "Cloud App Builder restored with strict iOS no-download/no-execution boundary for generated apps.",
            },
        )
        return release

    def _report(self, app, release):
        self.stdout.write("--- a-studio-builder-status ---")
        self.stdout.write(f"app_id={app.pk} package={app.package_name} bundle={app.bundle_id}")
        self.stdout.write("mobile_positioning=cloud_app_builder_no_generated_runtime")
        self.stdout.write(f"source_commit={ASTUDIO_COMMIT}")
        if release:
            self.stdout.write(f"release={release.version_name}({release.build_number}) status={release.status}")
            seen = set()
            for build in release.builds.order_by("platform"):
                seen.add(build.platform)
                self.stdout.write(f"build_{build.platform}={build.status} artifact={'yes' if build.artifact else 'no'} external_id={build.external_build_id or '-'}")
            for platform in ("android", "ios"):
                if platform not in seen:
                    self.stdout.write(f"build_{platform}=missing artifact=no external_id=-")
            for job in release.jobs.order_by("created_at"):
                self.stdout.write(f"job={job.type}:{job.status} error={(job.error or '-')[:500]}")
