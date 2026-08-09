from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.compliance.models import ComplianceRun
from apps.compliance.services import get_or_create_profile
from apps.compliance.tasks import execute_compliance_run
from apps.publisher.models import MobileApp


APP_SLUG = "a-studio"


class Command(BaseCommand):
    help = (
        "Apply A+ Studio Google Play API-managed compliance sections through Publisher. "
        "If Google blocks the Publisher server edge, the existing GitHub cloud fallback is dispatched."
    )

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=APP_SLUG).select_related("google_account").first()
        if not app:
            raise CommandError("A+ Studio is not registered in Publisher.")
        if not app.google_account or not app.google_account.configured:
            raise CommandError("A+ Studio Google Play account is not configured.")

        profile = get_or_create_profile(app)
        active = (
            profile.runs.filter(action="apply", status__in=["queued", "running"])
            .order_by("-created_at")
            .first()
        )
        if active:
            run = active
            self.stdout.write(f"compliance_run=reused id={run.pk} status={run.status}")
        else:
            run = ComplianceRun.objects.create(profile=profile, action="apply")
            self.stdout.write(f"compliance_run=created id={run.pk}")

        if run.status == "queued":
            execute_compliance_run.run(run.pk)
            run.refresh_from_db()

        self.stdout.write(f"run_id={run.pk}")
        self.stdout.write(f"run_status={run.status}")
        self.stdout.write(f"run_progress={run.progress}")
        self.stdout.write(
            "data_safety_template=" + ("present" if bool(profile.data_safety_template) else "missing")
        )
        self.stdout.write(
            "data_safety_csv=" + ("ready" if bool(profile.data_safety_csv.strip()) else "pending_template")
        )
        self.stdout.write("result=" + json.dumps(run.result or {}, ensure_ascii=False, sort_keys=True))
        if run.error:
            self.stdout.write("error=" + run.error)

        if run.status == "failed":
            raise CommandError(run.error or "A+ Studio Google compliance apply failed.")
        if run.status == "running":
            self.stdout.write(
                self.style.WARNING(
                    "google_apply=cloud_dispatched_or_still_running; wait for the compliance callback before retrying."
                )
            )
        elif run.status == "partial":
            self.stdout.write(
                self.style.WARNING(
                    "google_apply=partial; official API sections were applied and Console-only declarations remain."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("google_apply=succeeded"))
