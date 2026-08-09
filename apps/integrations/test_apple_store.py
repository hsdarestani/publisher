import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from .apple_store import AppleStoreClient
from .base import IntegrationError


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
            if path == "/apps/app-1/appStoreVersions?filter[platform]=IOS&limit=50":
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
            if path == "/apps/app-1/appStoreVersions?filter[platform]=IOS&limit=50":
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

    def test_localization_retries_without_whats_new_when_apple_state_blocks_it(self):
        client = self._client()
        app = SimpleNamespace(
            marketing_url="https://example.com",
            support_url="https://example.com/support",
        )
        loc = SimpleNamespace(
            locale="de-DE",
            full_description="Beschreibung",
            keywords="studio,ki",
            promotional_text="Erstellen Sie Ihre App.",
            release_notes="Erste Version",
            app=app,
        )
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == "GET":
                return {"data": [{"id": "loc-1"}]}
            body = json.loads(kwargs["data"])
            attrs = body["data"]["attributes"]
            if "whatsNew" in attrs:
                raise IntegrationError(
                    "Apple API 409: Attribute 'whatsNew' cannot be edited at this time"
                )
            return {"data": {"id": "loc-1", "attributes": attrs}}

        client.request = Mock(side_effect=request)

        result = client.set_localization("version-1", loc)

        self.assertEqual(result["id"], "loc-1")
        patch_calls = [call for call in calls if call[0] == "PATCH"]
        self.assertEqual(len(patch_calls), 2)
        first_attrs = json.loads(patch_calls[0][2]["data"])["data"]["attributes"]
        retry_attrs = json.loads(patch_calls[1][2]["data"])["data"]["attributes"]
        self.assertEqual(first_attrs["whatsNew"], "Erste Version")
        self.assertNotIn("whatsNew", retry_attrs)
        self.assertEqual(retry_attrs["description"], "Beschreibung")
