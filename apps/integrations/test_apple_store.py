import json
from unittest.mock import Mock

from django.test import SimpleTestCase

from .apple_store import AppleStoreClient


class AppleStoreVersionAlignmentTests(SimpleTestCase):
    def _client(self):
        return object.__new__(AppleStoreClient)

    def test_ensure_version_reuses_exact_match(self):
        client = self._client()
        exact = {
            "id": "version-exact",
            "attributes": {
                "versionString": "1.0.0",
                "appStoreState": "PREPARE_FOR_SUBMISSION",
            },
        }
        client.request = Mock(
            return_value={"data": [exact]},
        )

        result = client.ensure_version("app-1", "1.0.0")

        self.assertEqual(result, exact)
        client.request.assert_called_once_with(
            "GET",
            "/apps/app-1/appStoreVersions?filter[versionString]=1.0.0&limit=10",
        )

    def test_ensure_version_aligns_existing_editable_draft(self):
        client = self._client()
        draft = {
            "id": "version-draft",
            "attributes": {
                "versionString": "1.0",
                "appStoreState": "PREPARE_FOR_SUBMISSION",
            },
        }
        aligned = {
            "id": "version-draft",
            "attributes": {
                "versionString": "1.0.0",
                "appStoreState": "PREPARE_FOR_SUBMISSION",
            },
        }

        def request(method, path, **kwargs):
            if path == "/apps/app-1/appStoreVersions?filter[versionString]=1.0.0&limit=10":
                return {"data": []}
            if path == "/apps/app-1/appStoreVersions?filter[platform]=IOS&limit=50&sort=-createdDate":
                return {"data": [draft]}
            if method == "PATCH" and path == "/appStoreVersions/version-draft":
                body = json.loads(kwargs["data"])
                self.assertEqual(body["data"]["attributes"]["versionString"], "1.0.0")
                return {"data": aligned}
            self.fail(f"Unexpected Apple request: {method} {path}")

        client.request = Mock(side_effect=request)

        result = client.ensure_version("app-1", "1.0.0")

        self.assertEqual(result, aligned)
        self.assertEqual(result["attributes"]["versionString"], "1.0.0")

    def test_ensure_version_creates_only_when_no_editable_draft_exists(self):
        client = self._client()
        created = {
            "id": "version-created",
            "attributes": {"versionString": "1.0.0"},
        }

        def request(method, path, **kwargs):
            if path == "/apps/app-1/appStoreVersions?filter[versionString]=1.0.0&limit=10":
                return {"data": []}
            if path == "/apps/app-1/appStoreVersions?filter[platform]=IOS&limit=50&sort=-createdDate":
                return {
                    "data": [
                        {
                            "id": "old-version",
                            "attributes": {
                                "versionString": "0.9",
                                "appStoreState": "READY_FOR_DISTRIBUTION",
                            },
                        }
                    ]
                }
            if method == "POST" and path == "/appStoreVersions":
                body = json.loads(kwargs["data"])
                self.assertEqual(body["data"]["attributes"]["versionString"], "1.0.0")
                return {"data": created}
            self.fail(f"Unexpected Apple request: {method} {path}")

        client.request = Mock(side_effect=request)

        result = client.ensure_version("app-1", "1.0.0")

        self.assertEqual(result, created)
