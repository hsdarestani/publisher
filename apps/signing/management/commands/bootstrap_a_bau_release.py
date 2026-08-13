from __future__ import annotations

from django.utils import timezone

from apps.publisher.models import AppLocalization, Job, Release
from apps.signing.management.commands.bootstrap_a_bau import Command as ABBauBootstrapCommand


class Command(ABBauBootstrapCommand):
    help = "Run the production A+Bau Publisher release with Store-safe localization limits."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--recover-publish-after-restart",
            action="store_true",
            help="Fail only currently-running internal A+Bau Store publish jobs after a confirmed Publisher worker restart so they can be retried idempotently.",
        )

    def handle(self, *args, **options):
        if options.get("recover_publish_after_restart"):
            app = self._find_app()
            release = None
            if app:
                release = Release.objects.filter(
                    app=app,
                    version_name=options["app_version"],
                    build_number=options["build_number"],
                ).first()
            recovered = []
            if app and release:
                jobs = Job.objects.filter(
                    app=app,
                    release=release,
                    type__in=["submit_apple", "upload_google", "submit_google"],
                    status="running",
                    available_to_agents=False,
                ).order_by("created_at")
                for job in jobs:
                    job.status = "failed"
                    job.finished_at = timezone.now()
                    job.error = "Recovered after confirmed Publisher worker restart; safe to retry idempotently."
                    job.append_log(job.error)
                    job.save(update_fields=["status", "finished_at", "error", "updated_at"])
                    recovered.append(job.pk)
            self.stdout.write(
                "restart_recovered_publish_jobs="
                + (",".join(map(str, recovered)) if recovered else "none")
            )
        return super().handle(*args, **options)

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
                "short_description": "Aufträge, Termine, Zeiten, Baustellendoku, Aufmaß und Finanzen in einer App.",
                "full_description": full,
                "keywords": "Handwerk,Bau,Auftrag,Zeiterfassung,Aufmaß,Baustelle,Rechnung,Termin,Projekt",
                "promotional_text": "Von der Baustelle bis zur Rechnung: A+Bau verbindet Einsätze, Freigaben, Aufmaß, Finanzen und Büroarbeit in einem Ablauf.",
                "release_notes": (
                    "Neues A+Bau Branding und App-Icon. Verbesserte Angebote, Rechnungen und Finanzen. Neuer Monteur-zu-Büro-"
                    "Freigabeablauf, erweiterte Einsatzprüfung, bessere Zeiterfassung, Projektteam-Auswahl und rollenbasierte KI-Berechtigungen."
                ),
            },
        )
        self.stdout.write("localization=ready short_description_chars=76")

    def _upsert_assets(self, app):
        # Keep the base Android/iPhone assets, then add the 13-inch iPad set.
        # The generated Capacitor iOS app supports iPad, so App Store Connect
        # requires a valid iPad screenshot set before the version can be reviewed.
        super()._upsert_assets(app)
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
                platform="ios",
                filename=f"ios-ipad-13-{index+1}.png",
                data=self._screenshot_bytes(2048, 2732, index, title, subtitle),
                width=2048,
                height=2732,
                sort_order=index,
                device_type="APP_IPAD_PRO_3GEN_129",
            )
        self.stdout.write("ipad_store_assets=ready display=APP_IPAD_PRO_3GEN_129 size=2048x2732")
