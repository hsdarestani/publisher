from __future__ import annotations

from apps.publisher.models import AppLocalization
from apps.signing.management.commands.bootstrap_a_bau import Command as BaseCommand


class Command(BaseCommand):
    """A+Bau bootstrap with App Store/Play text constrained to Publisher DB limits.

    The original bootstrap used an 83-character short_description while the
    production schema stores that field as varchar(80), aborting the release
    transaction before a Release/Build could be created. Keep the existing
    orchestration but write a length-safe localization.
    """

    help = "Create/update and publish A+Bau with length-safe store localization."

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
                "release_notes": "Startproblem beim Öffnen behoben. A+Bau lädt jetzt zuverlässig auf iPhone und iPad; dazu kommen die neuesten Baustellen- und Kundenfunktionen.",
            },
        )
        self.stdout.write("localization=ready length_safe=true")
