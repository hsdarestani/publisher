from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp


APP_SLUG = "a-bau"
APP_VERSION = "2.2.2"


class Command(BaseCommand):
    help = "Read live A+Bau App Store privacy, version and review-submission resources without modifying them."

    def _call(self, client, path: str):
        try:
            return client.request("GET", path), None
        except Exception as exc:
            return None, exc

    def _print_call(self, client, label: str, path: str):
        payload, error = self._call(client, path)
        if error:
            self.stdout.write(f"{label}=ERROR {error}")
            return None
        compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.stdout.write(f"{label}={compact[:20000]}")
        return payload

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

        self._print_call(
            client,
            "app_store_version",
            f"/apps/{apple_id}/appStoreVersions?filter[versionString]={APP_VERSION}&include=build&limit=10",
        )

        probes = [
            ("privacy_app_data_usages", f"/apps/{apple_id}/dataUsages?limit=200"),
            ("privacy_app_data_usages_relationship", f"/apps/{apple_id}/relationships/dataUsages?limit=200"),
            ("privacy_publish_state", f"/apps/{apple_id}/dataUsagePublishState"),
            ("privacy_publish_state_relationship", f"/apps/{apple_id}/relationships/dataUsagePublishState"),
            ("privacy_direct_app_data_usages", f"/appDataUsages?filter[app]={apple_id}&limit=200"),
        ]
        for label, path in probes:
            self._print_call(client, label, path)

        submissions = []
        for state in (
            "READY_FOR_REVIEW",
            "WAITING_FOR_REVIEW",
            "IN_REVIEW",
            "UNRESOLVED_ISSUES",
            "CANCELING",
            "COMPLETING",
            "COMPLETE",
        ):
            payload = self._print_call(
                client,
                f"review_submissions_{state.lower()}",
                f"/apps/{apple_id}/reviewSubmissions?filter[state]={state}&limit=200",
            )
            if payload:
                submissions.extend(payload.get("data", []))

        seen = set()
        for submission in submissions:
            submission_id = submission.get("id")
            if not submission_id or submission_id in seen:
                continue
            seen.add(submission_id)
            self._print_call(
                client,
                f"review_submission_items_{submission_id}",
                f"/reviewSubmissions/{submission_id}/items?fields[reviewSubmissionItems]=state,appStoreVersion&include=appStoreVersion&limit=200",
            )

        self._print_call(
            client,
            "review_submissions_all",
            f"/apps/{apple_id}/reviewSubmissions?include=items&limit=200",
        )