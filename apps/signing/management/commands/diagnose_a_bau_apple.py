from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp


APP_SLUG = "a-bau"


class Command(BaseCommand):
    help = "Read live A+Bau App Store privacy and review-submission resources without modifying them."

    def _print_call(self, client, label: str, path: str):
        try:
            payload = client.request("GET", path)
        except Exception as exc:
            self.stdout.write(f"{label}=ERROR {exc}")
            return
        compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.stdout.write(f"{label}={compact[:12000]}")

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=APP_SLUG).select_related("apple_account").first()
        if not app:
            raise CommandError("A+Bau is not registered in Publisher.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+Bau Apple account is not configured.")

        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        apple_id = record["id"]
        self.stdout.write(f"apple_app_id={apple_id}")

        probes = [
            ("privacy_app_data_usages", f"/apps/{apple_id}/dataUsages?limit=200"),
            ("privacy_app_data_usages_relationship", f"/apps/{apple_id}/relationships/dataUsages?limit=200"),
            ("privacy_publish_state", f"/apps/{apple_id}/dataUsagePublishState"),
            ("privacy_publish_state_relationship", f"/apps/{apple_id}/relationships/dataUsagePublishState"),
            ("privacy_direct_app_data_usages", f"/appDataUsages?filter[app]={apple_id}&limit=200"),
        ]
        for label, path in probes:
            self._print_call(client, label, path)

        for state in ("READY_FOR_REVIEW", "WAITING_FOR_REVIEW", "IN_REVIEW"):
            self._print_call(
                client,
                f"review_submissions_{state.lower()}",
                f"/apps/{apple_id}/reviewSubmissions?filter[state]={state}&limit=200",
            )

        # Also read unfiltered submissions so a newly introduced state cannot be
        # hidden by our known-state list. This endpoint returns no credentials.
        self._print_call(
            client,
            "review_submissions_all",
            f"/apps/{apple_id}/reviewSubmissions?limit=200",
        )
