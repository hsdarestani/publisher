from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp


APP_SLUG = "a-bau"
APP_VERSION = "2.2.2"


class Command(BaseCommand):
    help = "Attach A+Bau to an existing empty Apple review draft and submit it without allocating another review slot."

    @staticmethod
    def _targets_version(client, submission, version_id):
        items = client.list_review_submission_items(submission["id"])
        for item in items:
            relationship = (
                item.get("relationships", {})
                .get("appStoreVersion", {})
                .get("data")
            )
            if relationship and str(relationship.get("id")) == str(version_id):
                return item, items
        return None, items

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=APP_SLUG).select_related("apple_account").first()
        if not app:
            raise CommandError("A+Bau is not registered in Publisher.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+Bau Apple account is not configured.")

        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        apple_app_id = record["id"]
        version = client.find_editable_version(apple_app_id, APP_VERSION)
        if not version:
            raise CommandError(f"Apple App Store version {APP_VERSION} was not found.")
        version_id = version["id"]

        # Idempotent success if this exact version already moved to review.
        for state in ("WAITING_FOR_REVIEW", "IN_REVIEW"):
            for submission in client.list_review_submissions(apple_app_id, state):
                item, _ = self._targets_version(client, submission, version_id)
                if item:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"apple_submission=already_submitted state={state} submission={submission['id']}"
                        )
                    )
                    return

        ready = client.list_review_submissions(apple_app_id, "READY_FOR_REVIEW")
        selected = None
        selected_item = None
        empty = None

        for submission in ready:
            item, items = self._targets_version(client, submission, version_id)
            if item:
                selected = submission
                selected_item = item
                break
            if not items and empty is None:
                empty = submission

        if selected is None:
            if empty is None:
                raise CommandError(
                    "No reusable empty READY_FOR_REVIEW draft exists. Refusing to create another Apple review slot."
                )
            selected = empty
            item_body = {
                "data": {
                    "type": "reviewSubmissionItems",
                    "relationships": {
                        "reviewSubmission": {
                            "data": {"type": "reviewSubmissions", "id": selected["id"]}
                        },
                        "appStoreVersion": {
                            "data": {"type": "appStoreVersions", "id": version_id}
                        },
                    },
                }
            }
            selected_item = client.request(
                "POST", "/reviewSubmissionItems", data=json.dumps(item_body)
            )["data"]
            self.stdout.write(
                f"apple_review_draft=reused submission={selected['id']} item={selected_item['id']}"
            )
        else:
            self.stdout.write(
                f"apple_review_draft=already_attached submission={selected['id']} item={selected_item['id']}"
            )

        submit_body = {
            "data": {
                "type": "reviewSubmissions",
                "id": selected["id"],
                "attributes": {"submitted": True},
            }
        }
        final = client.request(
            "PATCH",
            f"/reviewSubmissions/{selected['id']}",
            data=json.dumps(submit_body),
        )["data"]
        state = final.get("attributes", {}).get("state", "unknown")
        self.stdout.write(
            self.style.SUCCESS(
                f"apple_submission=submitted submission={selected['id']} state={state}"
            )
        )
