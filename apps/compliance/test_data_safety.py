from __future__ import annotations

import csv
import io
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.publisher.models import MobileApp
from scripts.google_play_cloud_operation import apply_payload, replace_image_group

from .data_safety import fill_data_safety_template
from .services import get_or_create_profile


class GoogleDataSafetyCsvTests(TestCase):
    def setUp(self):
        self.app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-data-safety-test",
            platform="android",
            package_name="de.freiraum.parking",
        )
        self.profile = get_or_create_profile(self.app)
        self.profile.data_practices = {
            "encrypted_in_transit": True,
            "deletion_request": True,
            "data_types": {
                "location.precise": {
                    "label": "Precise location",
                    "collected": True,
                    "shared": False,
                    "required": False,
                    "purposes": ["app_functionality"],
                },
                "personal_info.email": {
                    "label": "Email address",
                    "collected": True,
                    "shared": False,
                    "required": True,
                    "purposes": ["account_management"],
                },
            },
        }

    def test_single_choice_groups_have_exactly_one_true(self):
        template = io.StringIO()
        writer = csv.writer(template, lineterminator="\n")
        writer.writerow(
            [
                "Question ID (machine readable)",
                "Response ID (machine readable)",
                "Response value",
                "Answer requirement",
                "Human-friendly question label",
            ]
        )
        writer.writerows(
            [
                ["PSL_DATA_COLLECTION", "PSL_YES", "", "SINGLE_CHOICE", "Does your app collect or share data?\nYes"],
                ["PSL_DATA_COLLECTION", "PSL_NO", "", "SINGLE_CHOICE", "Does your app collect or share data?\nNo"],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:DATA_USAGE_USER_CONTROL",
                    "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL",
                    "",
                    "SINGLE_CHOICE",
                    "Data usage and handling (Precise location)\nIs this data required for your app?\nUsers can choose whether this data is collected",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:DATA_USAGE_USER_CONTROL",
                    "PSL_DATA_USAGE_USER_CONTROL_REQUIRED",
                    "",
                    "SINGLE_CHOICE",
                    "Data usage and handling (Precise location)\nIs this data required for your app?\nData collection is required",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_EMAIL_ADDRESS:DATA_USAGE_USER_CONTROL",
                    "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL",
                    "",
                    "SINGLE_CHOICE",
                    "Data usage and handling (Email address)\nIs this data required for your app?\nUsers can choose whether this data is collected",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_EMAIL_ADDRESS:DATA_USAGE_USER_CONTROL",
                    "PSL_DATA_USAGE_USER_CONTROL_REQUIRED",
                    "",
                    "SINGLE_CHOICE",
                    "Data usage and handling (Email address)\nIs this data required for your app?\nData collection is required",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:PSL_DATA_USAGE_COLLECTION_AND_SHARING",
                    "PSL_DATA_USAGE_ONLY_COLLECTED",
                    "",
                    "MULTIPLE_CHOICE",
                    "Data usage and handling (Precise location)\nIs this data collected, shared, or both?\nCollected",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:PSL_DATA_USAGE_COLLECTION_AND_SHARING",
                    "PSL_DATA_USAGE_ONLY_SHARED",
                    "",
                    "MULTIPLE_CHOICE",
                    "Data usage and handling (Precise location)\nIs this data collected, shared, or both?\nShared",
                ],
            ]
        )
        self.profile.data_safety_template = SimpleUploadedFile(
            "data-safety.csv", template.getvalue().encode("utf-8"), content_type="text/csv"
        )
        self.profile.save()

        output = fill_data_safety_template(self.profile)
        rows = list(csv.DictReader(io.StringIO(output)))
        grouped = {}
        for row in rows:
            if row["Answer requirement"] == "SINGLE_CHOICE":
                grouped.setdefault(row["Question ID (machine readable)"], []).append(row["Response value"])
        self.assertTrue(grouped)
        self.assertTrue(all(values.count("TRUE") == 1 for values in grouped.values()))

        by_response = {row["Response ID (machine readable)"]: row["Response value"] for row in rows}
        self.assertEqual(by_response["PSL_YES"], "TRUE")
        self.assertEqual(by_response["PSL_NO"], "")
        self.assertEqual(by_response["PSL_DATA_USAGE_USER_CONTROL_OPTIONAL"], "")  # last duplicate key is email
        precise_optional = next(
            row for row in rows if "PRECISE_LOCATION" in row["Question ID (machine readable)"] and row["Response ID (machine readable)"].endswith("OPTIONAL")
        )
        email_required = next(
            row for row in rows if "EMAIL_ADDRESS" in row["Question ID (machine readable)"] and row["Response ID (machine readable)"].endswith("REQUIRED")
        )
        self.assertEqual(precise_optional["Response value"], "TRUE")
        self.assertEqual(email_required["Response value"], "TRUE")
        self.assertEqual(by_response["PSL_DATA_USAGE_ONLY_COLLECTED"], "TRUE")
        self.assertEqual(by_response["PSL_DATA_USAGE_ONLY_SHARED"], "")


class GoogleCloudPartialResultTests(TestCase):
    @patch("scripts.google_play_cloud_operation.AuthorizedSession")
    @patch("scripts.google_play_cloud_operation.create_edit", return_value="edit-1")
    def test_data_safety_rejection_does_not_erase_successful_store_commit(self, create_edit, session_class):
        session = Mock()
        session_class.return_value = session
        session.put.return_value = Mock(ok=True, content=b"{}", json=lambda: {})
        session.delete.return_value = Mock(ok=True, content=b"", json=lambda: {})
        success_response = Mock(ok=True, content=b"{}", json=lambda: {"id": "edit-1"})
        rejected_response = Mock(
            ok=False,
            status_code=400,
            content=b"{}",
            text="invalid safety labels",
            json=lambda: {"error": {"message": "Selected more than one response"}},
        )
        session.post.side_effect = [success_response, success_response, rejected_response]

        result = apply_payload(
            {
                "package_name": "de.freiraum.parking",
                "localizations": [
                    {
                        "locale": "de-DE",
                        "title": "FREIRAUM",
                        "short_description": "Parkplätze finden",
                        "full_description": "Parkplätze finden und reservieren",
                    }
                ],
                "assets": [],
                "data_safety_csv": "Question ID,Response value\nQ1,TRUE\n",
            },
            Mock(),
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["data_safety_applied"])
        self.assertIn("Selected more than one response", result["data_safety_error"])
        self.assertEqual(result["listing_count"], 1)


class GoogleCloudImageRetryTests(TestCase):
    @patch("scripts.google_play_cloud_operation.time.sleep")
    def test_transient_feature_graphic_500_clears_and_retries_whole_group(self, sleep):
        session = Mock()
        session.delete.return_value = Mock(ok=True, content=b"", json=lambda: {})
        transient = Mock(
            ok=False,
            status_code=500,
            content=b"{}",
            text="internal",
            json=lambda: {"error": {"message": "Internal error encountered."}},
        )
        success = Mock(ok=True, status_code=200, content=b"{}", json=lambda: {"sha256": "ok"})
        session.post.side_effect = [transient, success]

        uploaded = replace_image_group(
            session,
            "de.freiraum.parking",
            "edit-1",
            "de-DE",
            "featureGraphic",
            [
                {
                    "content": b"png",
                    "content_type": "image/png",
                    "sort_order": 0,
                }
            ],
            attempts=2,
        )

        self.assertEqual(uploaded, 1)
        self.assertEqual(session.delete.call_count, 2)
        self.assertEqual(session.post.call_count, 2)
        sleep.assert_called_once()
