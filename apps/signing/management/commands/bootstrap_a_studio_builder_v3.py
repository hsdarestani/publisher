from __future__ import annotations

import json
import time

from apps.integrations.apple_store import AppleStoreClient
from apps.signing.management.commands import bootstrap_a_studio_builder_v2 as builder_v2


# App Store Connect changes an app-version item to READY_FOR_REVIEW as soon as
# it is added to a draft submission. At that point screenshots are immutable.
# When Build 10 needs to replace the rejected Build 8/9 screenshots, detach the
# version item first, edit the version, then put it back into the same draft.
# Apple exposes DELETE /reviewSubmissionItems/{id} specifically for this flow.
_original_submit_version = AppleStoreClient.submit_version


def _submit_version_reusing_detached_draft(self, app_id, version_id):
    ready = self.list_review_submissions(app_id, "READY_FOR_REVIEW")
    for submission in ready:
        item, _ = self._review_submission_matches(submission, version_id)
        if item:
            # The normal implementation already handles an attached draft.
            return _original_submit_version(self, app_id, version_id)

    # A draft can remain after its version item was detached to unlock metadata.
    # Reuse it instead of allocating a second review-submission slot.
    if ready:
        submission = ready[0]
        item_body = {
            "data": {
                "type": "reviewSubmissionItems",
                "relationships": {
                    "reviewSubmission": {
                        "data": {"type": "reviewSubmissions", "id": submission["id"]}
                    },
                    "appStoreVersion": {
                        "data": {"type": "appStoreVersions", "id": str(version_id)}
                    },
                },
            }
        }
        item = self.request(
            "POST", "/reviewSubmissionItems", data=json.dumps(item_body)
        )["data"]
        submit_body = {
            "data": {
                "type": "reviewSubmissions",
                "id": submission["id"],
                "attributes": {"submitted": True},
            }
        }
        final = self.request(
            "PATCH",
            f"/reviewSubmissions/{submission['id']}",
            data=json.dumps(submit_body),
        )["data"]
        return {"submission": final, "item": item, "reused": True}

    return _original_submit_version(self, app_id, version_id)


AppleStoreClient.submit_version = _submit_version_reusing_detached_draft


class Command(builder_v2.Command):
    help = (
        "Submit A+ Studio Build 10 Cloud App Builder after safely unlocking "
        "the App Store version for metadata and screenshot replacement."
    )

    def _unlock_version_for_store_edits(self, client, app_id, version_id):
        # The original rejection may still be UNRESOLVED_ISSUES with the item
        # already changed to READY_FOR_REVIEW by an earlier resolution attempt.
        # Remove the exact matching version item regardless of its item state.
        for state in ("UNRESOLVED_ISSUES", "READY_FOR_REVIEW"):
            for submission in client.list_review_submissions(app_id, state):
                item, _ = client._review_submission_matches(submission, version_id)
                if not item:
                    continue
                client.request("DELETE", f"/reviewSubmissionItems/{item['id']}")
                self.stdout.write(
                    f"apple_review_item=detached submission={submission['id']} "
                    f"item={item['id']} previous_submission_state={state}"
                )

                # App Store Connect updates the app-version state asynchronously.
                # Do not start deleting screenshots until READY_FOR_REVIEW clears.
                for _ in range(12):
                    version = client.request("GET", f"/appStoreVersions/{version_id}").get("data") or {}
                    attrs = version.get("attributes", {})
                    version_state = attrs.get("appStoreState") or attrs.get("appVersionState") or ""
                    if version_state != "READY_FOR_REVIEW":
                        self.stdout.write(
                            f"apple_version_editable_state={version_state or 'unknown'}"
                        )
                        return
                    time.sleep(2)
                # Even if the state field lags, the item is detached; allow the
                # subsequent API call to provide the authoritative result.
                return

    def _submit_ios(self, app, release, build):
        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        version = client.ensure_version(record["id"], release.version_name)
        self._unlock_version_for_store_edits(client, record["id"], version["id"])
        return super()._submit_ios(app, release, build)
