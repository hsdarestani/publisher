import json
from unittest.mock import Mock

from django.test import SimpleTestCase

from .apple_compliance import (
    apply_app_store_compliance,
    find_editable_app_info,
    set_age_rating_declaration,
    set_content_rights,
)
from .base import IntegrationError


class AppleAppComplianceTests(SimpleTestCase):
    def test_content_rights_uses_app_update_request(self):
        client = Mock()
        client.request.return_value = {
            "data": {
                "type": "apps",
                "id": "app-1",
                "attributes": {
                    "contentRightsDeclaration": "USES_THIRD_PARTY_CONTENT"
                },
            }
        }

        result = set_content_rights(
            client,
            "app-1",
            "USES_THIRD_PARTY_CONTENT",
        )

        self.assertEqual(
            result["attributes"]["contentRightsDeclaration"],
            "USES_THIRD_PARTY_CONTENT",
        )
        method, path = client.request.call_args.args
        body = json.loads(client.request.call_args.kwargs["data"])
        self.assertEqual(method, "PATCH")
        self.assertEqual(path, "/apps/app-1")
        self.assertEqual(body["data"]["type"], "apps")
        self.assertEqual(
            body["data"]["attributes"]["contentRightsDeclaration"],
            "USES_THIRD_PARTY_CONTENT",
        )

    def test_invalid_content_rights_value_is_rejected_locally(self):
        with self.assertRaises(ValueError):
            set_content_rights(Mock(), "app-1", "MAYBE")

    def test_find_editable_app_info_prefers_prepare_for_submission(self):
        client = Mock()
        client.request.return_value = {
            "data": [
                {
                    "id": "live-info",
                    "attributes": {"appStoreState": "READY_FOR_DISTRIBUTION"},
                },
                {
                    "id": "draft-info",
                    "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION"},
                },
            ]
        }

        result = find_editable_app_info(client, "app-1")

        self.assertEqual(result["id"], "draft-info")
        client.request.assert_called_once_with(
            "GET",
            "/apps/app-1/appInfos?limit=50",
        )

    def test_find_editable_app_info_does_not_guess_between_noneditable_records(self):
        client = Mock()
        client.request.return_value = {
            "data": [
                {"id": "one", "attributes": {"appStoreState": "READY_FOR_DISTRIBUTION"}},
                {"id": "two", "attributes": {"appStoreState": "READY_FOR_DISTRIBUTION"}},
            ]
        }

        with self.assertRaises(IntegrationError):
            find_editable_app_info(client, "app-1")

    def test_age_rating_uses_age_rating_update_request(self):
        client = Mock()
        client.request.return_value = {
            "data": {
                "type": "ageRatingDeclarations",
                "id": "rating-1",
                "attributes": {
                    "userGeneratedContent": True,
                    "messagingAndChat": False,
                    "profanityOrCrudeHumor": "NONE",
                },
            }
        }
        attrs = {
            "userGeneratedContent": True,
            "messagingAndChat": False,
            "profanityOrCrudeHumor": "NONE",
        }

        result = set_age_rating_declaration(client, "rating-1", attrs)

        self.assertTrue(result["attributes"]["userGeneratedContent"])
        method, path = client.request.call_args.args
        body = json.loads(client.request.call_args.kwargs["data"])
        self.assertEqual(method, "PATCH")
        self.assertEqual(path, "/ageRatingDeclarations/rating-1")
        self.assertEqual(body["data"]["type"], "ageRatingDeclarations")
        self.assertEqual(body["data"]["attributes"], attrs)

    def test_apply_compliance_updates_content_rights_and_age_rating(self):
        client = Mock()

        def request(method, path, **kwargs):
            if method == "PATCH" and path == "/apps/app-1":
                return {
                    "data": {
                        "id": "app-1",
                        "type": "apps",
                        "attributes": {
                            "contentRightsDeclaration": "USES_THIRD_PARTY_CONTENT"
                        },
                    }
                }
            if method == "GET" and path == "/apps/app-1/appInfos?limit=50":
                return {
                    "data": [
                        {
                            "id": "info-1",
                            "type": "appInfos",
                            "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION"},
                        }
                    ]
                }
            if method == "GET" and path == "/appInfos/info-1/ageRatingDeclaration":
                return {
                    "data": {
                        "id": "rating-1",
                        "type": "ageRatingDeclarations",
                        "attributes": {},
                    }
                }
            if method == "PATCH" and path == "/ageRatingDeclarations/rating-1":
                body = json.loads(kwargs["data"])
                return {
                    "data": {
                        "id": "rating-1",
                        "type": "ageRatingDeclarations",
                        "attributes": body["data"]["attributes"],
                    }
                }
            self.fail(f"Unexpected request: {method} {path}")

        client.request.side_effect = request
        profile = {
            "userGeneratedContent": True,
            "messagingAndChat": False,
            "contests": "NONE",
        }

        result = apply_app_store_compliance(
            client,
            "app-1",
            content_rights="USES_THIRD_PARTY_CONTENT",
            age_rating=profile,
        )

        self.assertEqual(result["content_rights"], "USES_THIRD_PARTY_CONTENT")
        self.assertEqual(result["age_rating_declaration_id"], "rating-1")
        self.assertEqual(result["age_rating"], profile)
