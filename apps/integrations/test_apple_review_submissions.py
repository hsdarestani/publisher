import json
from unittest.mock import Mock

from django.test import SimpleTestCase

from .apple_store import AppleStoreClient


def version_item(item_id, version_id):
    return {
        "id": item_id,
        "type": "reviewSubmissionItems",
        "relationships": {
            "appStoreVersion": {
                "data": {"type": "appStoreVersions", "id": version_id}
            }
        },
    }


class AppleReviewSubmissionRetryTests(SimpleTestCase):
    def _client(self):
        return object.__new__(AppleStoreClient)

    def test_reuses_first_ready_submission_without_cancelling_other_drafts(self):
        client = self._client()
        submissions = [
            {"id": "sub-1", "attributes": {"state": "READY_FOR_REVIEW"}},
            {"id": "sub-2", "attributes": {"state": "READY_FOR_REVIEW"}},
        ]
        item_1 = version_item("item-1", "version-1")
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path.endswith("filter[state]=WAITING_FOR_REVIEW&limit=200"):
                return {"data": []}
            if path.endswith("filter[state]=IN_REVIEW&limit=200"):
                return {"data": []}
            if path.endswith("filter[state]=READY_FOR_REVIEW&limit=200"):
                return {"data": submissions}
            if path.startswith("/reviewSubmissions/sub-1/items?"):
                return {"data": [item_1]}
            if method == "PATCH" and path == "/reviewSubmissions/sub-1":
                body = json.loads(kwargs["data"])
                self.assertIs(body["data"]["attributes"]["submitted"], True)
                return {"data": {"id": "sub-1", "attributes": {"state": "WAITING_FOR_REVIEW"}}}
            self.fail(f"Unexpected Apple request: {method} {path}")

        client.request = Mock(side_effect=request)

        result = client.submit_version("app-1", "version-1")

        self.assertEqual(result["submission"]["id"], "sub-1")
        self.assertTrue(result["reused"])
        self.assertFalse(any(method == "POST" for method, _, _ in calls))
        self.assertFalse(
            any(
                method == "PATCH"
                and json.loads(kwargs["data"])["data"]["attributes"].get("canceled")
                for method, _, kwargs in calls
                if "data" in kwargs
            )
        )

    def test_matching_waiting_submission_is_already_submitted(self):
        client = self._client()
        waiting = {"id": "sub-wait", "attributes": {"state": "WAITING_FOR_REVIEW"}}
        item = version_item("item-wait", "version-1")
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path.endswith("filter[state]=WAITING_FOR_REVIEW&limit=200"):
                return {"data": [waiting]}
            if path.startswith("/reviewSubmissions/sub-wait/items?"):
                return {"data": [item]}
            self.fail(f"Unexpected Apple request: {method} {path}")

        client.request = Mock(side_effect=request)

        result = client.submit_version("app-1", "version-1")

        self.assertEqual(result["submission"]["id"], "sub-wait")
        self.assertTrue(result["already_submitted"])
        self.assertFalse(any(method in {"POST", "PATCH"} for method, _, _ in calls))

    def test_creates_new_submission_only_when_no_ready_draft_targets_version(self):
        client = self._client()
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path.endswith("filter[state]=WAITING_FOR_REVIEW&limit=200"):
                return {"data": []}
            if path.endswith("filter[state]=IN_REVIEW&limit=200"):
                return {"data": []}
            if path.endswith("filter[state]=READY_FOR_REVIEW&limit=200"):
                return {"data": [{"id": "empty-sub", "attributes": {"state": "READY_FOR_REVIEW"}}]}
            if path.startswith("/reviewSubmissions/empty-sub/items?"):
                return {"data": []}
            if method == "POST" and path == "/reviewSubmissions":
                return {"data": {"id": "new-sub", "attributes": {"state": "READY_FOR_REVIEW"}}}
            if method == "POST" and path == "/reviewSubmissionItems":
                return {"data": version_item("new-item", "version-1")}
            if method == "PATCH" and path == "/reviewSubmissions/new-sub":
                return {"data": {"id": "new-sub", "attributes": {"state": "WAITING_FOR_REVIEW"}}}
            self.fail(f"Unexpected Apple request: {method} {path}")

        client.request = Mock(side_effect=request)

        result = client.submit_version("app-1", "version-1")

        self.assertEqual(result["submission"]["id"], "new-sub")
        self.assertFalse(result["reused"])
        self.assertFalse(
            any(
                method == "PATCH" and path == "/reviewSubmissions/empty-sub"
                for method, path, _ in calls
            )
        )
