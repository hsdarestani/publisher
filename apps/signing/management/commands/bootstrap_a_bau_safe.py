from __future__ import annotations

from apps.publisher.models import AppLocalization
from apps.signing.management.commands.bootstrap_a_bau import Command as BaseCommand


class Command(BaseCommand):
    """A+Bau bootstrap with App Store/Play text constrained to Publisher DB limits.

    The original bootstrap used an 83-character short_description while the
    production schema stores that field as varchar(80), aborting the release
    transaction before a Release/Build could be created. Keep the existing
    orchestration but write a length-safe localization.

    iOS App Store screenshots are intentionally NOT synthesized here. Apple
    Guideline 2.3.3 requires screenshots to show the current app in use, so the
    iOS media is captured from the authenticated live A+Bau UI by the dedicated
    release workflow and then preserved across later bootstrap runs.
    """

    help = "Create/update and publish A+Bau with length-safe store localization."

    def _upsert_app(self, app):
        app = super()._upsert_app(app)
        app.review_notes = (
            "A+Bau ist eine B2B-App für Handwerks- und Baubetriebe. Bitte die im App Review / App Access Feld hinterlegten "
            "Demo-Zugangsdaten verwenden. Wichtiger Hinweis für Guideline 2.1(a): Der Button 'Scannen' bleibt auf allen "
            "unterstützten iPhone- und iPad-Geräten aktiv. Auf Geräten mit LiDAR wird Apple RoomPlan geöffnet. Auf Geräten ohne "
            "LiDAR, insbesondere iPad Air 11-inch (M3), öffnet derselbe Button ein natives manuelles Raumaufmaß für Länge, Breite "
            "und Höhe. Dieses Aufmaß kann gespeichert und zum Projekt hochgeladen werden; ein USDZ-Modell ist im manuellen Modus "
            "nicht erforderlich. Testweg: anmelden → 'Raum scannen' → beliebiges Demo-Projekt → 'Scannen'. Kamera und Mikrofon werden "
            "nur nach einer aktiven Aktion angefragt. Optionale KI-Funktionen benötigen eine separate Einwilligung. "
            "Die App-Store-Screenshots zeigen die aktuelle, authentifizierte A+Bau-Oberfläche in Benutzung und wurden nach dem "
            "Guideline-2.3.3-Hinweis aktualisiert. "
            "Kontolöschung: https://kayi.smarbiz.sbs/konto-loeschen/ · Datenschutz: https://kayi.smarbiz.sbs/datenschutz/ · "
            "Support: https://kayi.smarbiz.sbs/support/."
        )
        app.save(update_fields=["review_notes"])
        self.stdout.write("review_notes=ipad_non_lidar_fallback+real_store_screenshots")
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
        short_description = "Aufträge, Termine, Zeiterfassung, Doku, Aufmaß und Finanzen in einer App."
        assert len(short_description) <= 80
        AppLocalization.objects.update_or_create(
            app=app,
            locale="de-DE",
            defaults={
                "title": "A+Bau",
                "subtitle": "Baustelle. Büro. Im Griff.",
                "short_description": short_description,
                "full_description": full,
                "keywords": "Handwerk,Bau,Auftrag,Zeiterfassung,Aufmaß,Baustelle,Rechnung,Termin,Projekt",
                "promotional_text": "Von der Baustelle bis zur Rechnung: A+Bau verbindet Einsätze, Freigaben, Aufmaß, Finanzen und Büroarbeit in einem Ablauf.",
                "release_notes": "Raumaufmaß auf iPad verbessert: 'Scannen' bleibt jetzt auch ohne LiDAR aktiv und öffnet dort ein manuelles Aufmaß. Auf LiDAR-Geräten wird weiterhin Apple RoomPlan verwendet.",
            },
        )
        self.stdout.write("localization=ready length_safe=true")

    def _upsert_assets(self, app):
        """Generate Android store art while preserving real iOS screenshots.

        The base command used Pillow to draw illustrative iOS screenshots. Apple
        rejected those under Guideline 2.3.3 because they were not captures of
        the current app. Never overwrite the real iOS captures stored in AppAsset.
        """
        self._save_asset(
            app,
            kind="icon",
            platform="shared",
            filename="a-bau-fav-512.png",
            data=self._icon_bytes(),
            width=512,
            height=512,
        )
        self._save_asset(
            app,
            kind="feature_graphic",
            platform="android",
            filename="a-bau-feature-1024x500.png",
            data=self._feature_bytes(),
            width=1024,
            height=500,
        )
        frames = [
            ("Alles an einem Ort.", "Projekte, Kunden und Termine übersichtlich verwalten."),
            ("Direkt auf der Baustelle.", "Zeit, Fotos, Berichte und Aufmaß im Einsatz dokumentieren."),
            ("Erst prüfen. Dann freigeben.", "Monteur, Büro und Kunde in einem nachvollziehbaren Ablauf."),
            ("Von der Kalkulation zur Rechnung.", "Preise, Margen, Finanzen und KI nur für berechtigte Rollen."),
        ]
        for index, (title, subtitle) in enumerate(frames):
            self._save_asset(
                app,
                kind="screenshot",
                platform="android",
                filename=f"android-{index + 1}.png",
                data=self._screenshot_bytes(1080, 1920, index, title, subtitle),
                width=1080,
                height=1920,
                sort_order=index,
                device_type="phone",
            )
        self.stdout.write("store_assets=ready android_generated=true ios=preserved_real_capture")

    def _upsert_release(self, app, version, build_number):
        release = super()._upsert_release(app, version, build_number)
        release.release_notes = (
            "App-Store-Fix für iPad ohne LiDAR: Scannen bleibt aktiv und bietet ein natives manuelles Raumaufmaß; "
            "LiDAR-Geräte verwenden weiterhin Apple RoomPlan."
        )
        release.save(update_fields=["release_notes", "updated_at"])
        return release
