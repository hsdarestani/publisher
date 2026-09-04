from __future__ import annotations

import json
import time

from apps.integrations.apple_store import AppleStoreClient
from apps.signing.management.commands import bootstrap_a_studio_builder_v3 as builder_v3


class Command(builder_v3.Command):
    help = (
        "Finalize A+ Studio Build 10 by removing the previously-submitted "
        "rejected review item before replacing App Store metadata."
    )

    def _wait_until_version_leaves_ready_for_review(self, client, version_id):
        for _ in range(20):
            version = client.request("GET", f"/appStoreVersions/{version_id}").get("data") or {}
            attrs = version.get("attributes", {})
            state = attrs.get("appStoreState") or attrs.get("appVersionState") or ""
            if state != "READY_FOR_REVIEW":
                self.stdout.write(f"apple_version_editable_state={state or 'unknown'}")
                return
            time.sleep(2)
        self.stdout.write("apple_version_state=ready_for_review_state_lag")

    def _unlock_version_for_store_edits(self, client, app_id, version_id):
        # A rejected item that was already submitted cannot be deleted. Apple
        # exposes reviewSubmissionItem.attributes.removed for exactly this case.
        # Removing it completes/unblocks the old unresolved submission; the app
        # version can then be edited and submitted again in a fresh submission.
        for submission in client.list_review_submissions(app_id, "UNRESOLVED_ISSUES"):
            item, _ = client._review_submission_matches(submission, version_id)
            if not item:
                continue
            body = {
                "data": {
                    "type": "reviewSubmissionItems",
                    "id": item["id"],
                    "attributes": {"removed": True},
                }
            }
            updated = client.request(
                "PATCH",
                f"/reviewSubmissionItems/{item['id']}",
                data=json.dumps(body),
            ).get("data") or {}
            self.stdout.write(
                "apple_review_item=removed "
                f"submission={submission['id']} item={item['id']} "
                f"state={updated.get('attributes', {}).get('state', '')}"
            )
            self._wait_until_version_leaves_ready_for_review(client, version_id)
            return

        # If the old unresolved submission has already been converted to a pure
        # draft, its item has never been submitted in that draft and DELETE is
        # the correct operation. This fallback is primarily for idempotent retry.
        for submission in client.list_review_submissions(app_id, "READY_FOR_REVIEW"):
            item, _ = client._review_submission_matches(submission, version_id)
            if not item:
                continue
            try:
                client.request("DELETE", f"/reviewSubmissionItems/{item['id']}")
                self.stdout.write(
                    f"apple_review_item=detached_draft submission={submission['id']} item={item['id']}"
                )
            except Exception as exc:
                # A draft may still be backed by the previously-submitted item.
                # In that case use Apple's submitted-item removal attribute.
                if "Item was already submitted" not in str(exc):
                    raise
                body = {
                    "data": {
                        "type": "reviewSubmissionItems",
                        "id": item["id"],
                        "attributes": {"removed": True},
                    }
                }
                client.request(
                    "PATCH",
                    f"/reviewSubmissionItems/{item['id']}",
                    data=json.dumps(body),
                )
                self.stdout.write(
                    f"apple_review_item=removed_submitted_draft submission={submission['id']} item={item['id']}"
                )
            self._wait_until_version_leaves_ready_for_review(client, version_id)
            return
