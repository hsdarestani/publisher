from __future__ import annotations

import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.publisher.models import MobileApp

from .data_safety import fill_data_safety_template
from .services import get_or_create_profile


HEADERS = [
    "Question ID (machine readable)",
    "Response ID (machine readable)",
    "Response value",
    "Answer requirement",
    "Human-friendly question label",
]


@override_settings(PUBLIC_URL="https://publisher.example.test")
class RequiredDataSafetyAnswerTests(TestCase):
    def setUp(self):
        self.app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-required-data-safety",
            client_name="A+ Solution GmbH",
            platform="android",
            package_name="de.freiraum.parking",
            requires_login=True,
        )
        self.profile = get_or_create_profile(self.app)
        self.profile.app_access = "login"
        self.profile.account_deletion = "support"
        self.profile.support_email = "support@example.test"
        self.profile.data_practices = {
            "account_creation": True,
            "encrypted_in_transit": True,
            "deletion_request": True,
            "data_types": {
                "personal_info.email": {
                    "label": "Email address",
                    "collected": True,
                    "shared": False,
                    "required": True,
                    "purposes": ["account_management"],
                },
                "location.precise": {
                    "label": "Precise location",
                    "collected": True,
                    "shared": False,
                    "required": False,
                    "purposes": ["app_functionality"],
                },
                "financial_info.purchase_history": {
                    "label": "Purchase history",
                    "collected": True,
                    "shared": False,
                    "required": False,
                    "purposes": ["app_functionality"],
                },
                "files.documents": {
                    "label": "Files and docs",
                    "collected": True,
                    "shared": False,
                    "required": False,
                    "purposes": ["app_functionality"],
                },
            },
        }
        self.profile.save()

    def _template(self):
        rows = [
            ["PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA", "", "", "REQUIRED", "Does your app collect or share any required user data types?"],
            ["PSL_DATA_COLLECTION_ENCRYPTED_IN_TRANSIT", "", "", "MAYBE_REQUIRED", "Is all data encrypted in transit?"],
            ["PSL_SUPPORTED_ACCOUNT_CREATION_METHODS", "PSL_ACM_USER_ID_PASSWORD", "", "MULTIPLE_CHOICE", "User ID and password"],
            ["PSL_SUPPORTED_ACCOUNT_CREATION_METHODS", "PSL_ACM_NONE", "", "MULTIPLE_CHOICE", "No account creation"],
            ["PSL_ACCOUNT_DELETION_URL", "", "", "MAYBE_REQUIRED", "Account deletion URL"],
            ["PSL_SUPPORT_DATA_DELETION_BY_USER", "DATA_DELETION_YES", "", "SINGLE_CHOICE", "Can users request deletion? / Yes"],
            ["PSL_SUPPORT_DATA_DELETION_BY_USER", "DATA_DELETION_NO", "", "SINGLE_CHOICE", "Can users request deletion? / No"],
            ["PSL_SUPPORT_DATA_DELETION_BY_USER", "DATA_DELETION_NO_AUTO_DELETED", "", "SINGLE_CHOICE", "Automatically deleted"],
            ["PSL_DATA_DELETION_URL", "", "", "MAYBE_REQUIRED", "Delete data URL"],
            ["PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL", "", "MULTIPLE_CHOICE", "Personal info / Email address"],
            ["PSL_DATA_TYPES_LOCATION", "PSL_PRECISE_LOCATION", "", "MULTIPLE_CHOICE", "Location / Precise location"],
            ["PSL_DATA_TYPES_FINANCIAL", "PSL_PURCHASE_HISTORY", "", "MULTIPLE_CHOICE", "Financial info / Purchase history"],
            ["PSL_DATA_TYPES_FILES_AND_DOCS", "PSL_FILES_AND_DOCS", "", "MULTIPLE_CHOICE", "Files and docs / Files and docs"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_COLLECTION_AND_SHARING", "PSL_DATA_USAGE_ONLY_COLLECTED", "", "MULTIPLE_CHOICE", "Email / Collected"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_COLLECTION_AND_SHARING", "PSL_DATA_USAGE_ONLY_SHARED", "", "MULTIPLE_CHOICE", "Email / Shared"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL", "", "", "MAYBE_REQUIRED", "Is email processed ephemerally?"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_USER_CONTROL", "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL", "", "SINGLE_CHOICE", "Email / Optional"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_USER_CONTROL", "PSL_DATA_USAGE_USER_CONTROL_REQUIRED", "", "SINGLE_CHOICE", "Email / Required"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_COLLECTION_PURPOSE", "PSL_ACCOUNT_MANAGEMENT", "", "MULTIPLE_CHOICE", "Email / Account management"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:PSL_DATA_USAGE_COLLECTION_AND_SHARING", "PSL_DATA_USAGE_ONLY_COLLECTED", "", "MULTIPLE_CHOICE", "Precise location / Collected"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:PSL_DATA_USAGE_EPHEMERAL", "", "", "MAYBE_REQUIRED", "Is precise location processed ephemerally?"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:DATA_USAGE_USER_CONTROL", "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL", "", "SINGLE_CHOICE", "Precise location / Optional"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:DATA_USAGE_USER_CONTROL", "PSL_DATA_USAGE_USER_CONTROL_REQUIRED", "", "SINGLE_CHOICE", "Precise location / Required"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:DATA_USAGE_COLLECTION_PURPOSE", "PSL_APP_FUNCTIONALITY", "", "MULTIPLE_CHOICE", "Precise location / App functionality"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_PURCHASE_HISTORY:PSL_DATA_USAGE_COLLECTION_AND_SHARING", "PSL_DATA_USAGE_ONLY_COLLECTED", "", "MULTIPLE_CHOICE", "Purchase history / Collected"],
            ["PSL_DATA_USAGE_RESPONSES:PSL_FILES_AND_DOCS:PSL_DATA_USAGE_COLLECTION_AND_SHARING", "PSL_DATA_USAGE_ONLY_COLLECTED", "", "MULTIPLE_CHOICE", "Files and docs / Collected"],
        ]
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADERS)
        writer.writerows(rows)
        return stream.getvalue()

    def test_required_parent_urls_data_types_and_usage_are_filled(self):
        self.profile.data_safety_template = SimpleUploadedFile(
            "data-safety.csv", self._template().encode("utf-8"), content_type="text/csv"
        )
        self.profile.save()

        output = fill_data_safety_template(self.profile)
        rows = list(csv.DictReader(io.StringIO(output)))
        values = {
            (row[HEADERS[0]], row[HEADERS[1]]): row[HEADERS[2]]
            for row in rows
        }

        self.assertEqual(values[("PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA", "")], "TRUE")
        self.assertEqual(values[("PSL_DATA_COLLECTION_ENCRYPTED_IN_TRANSIT", "")], "TRUE")
        self.assertEqual(values[("PSL_SUPPORTED_ACCOUNT_CREATION_METHODS", "PSL_ACM_USER_ID_PASSWORD")], "TRUE")
        self.assertEqual(values[("PSL_SUPPORTED_ACCOUNT_CREATION_METHODS", "PSL_ACM_NONE")], "")
        self.assertEqual(
            values[("PSL_ACCOUNT_DELETION_URL", "")],
            "https://publisher.example.test/compliance/delete-account/freiraum-required-data-safety/",
        )
        self.assertEqual(values[("PSL_SUPPORT_DATA_DELETION_BY_USER", "DATA_DELETION_YES")], "TRUE")
        self.assertEqual(values[("PSL_SUPPORT_DATA_DELETION_BY_USER", "DATA_DELETION_NO")], "")
        self.assertEqual(values[("PSL_DATA_DELETION_URL", "")], values[("PSL_ACCOUNT_DELETION_URL", "")])
        self.assertEqual(values[("PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL")], "TRUE")
        self.assertEqual(values[("PSL_DATA_TYPES_LOCATION", "PSL_PRECISE_LOCATION")], "TRUE")
        self.assertEqual(values[("PSL_DATA_TYPES_FINANCIAL", "PSL_PURCHASE_HISTORY")], "TRUE")
        self.assertEqual(values[("PSL_DATA_TYPES_FILES_AND_DOCS", "PSL_FILES_AND_DOCS")], "TRUE")
        self.assertEqual(values[("PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL", "")], "FALSE")
        self.assertEqual(values[("PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_USER_CONTROL", "PSL_DATA_USAGE_USER_CONTROL_REQUIRED")], "TRUE")
        self.assertEqual(values[("PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_COLLECTION_PURPOSE", "PSL_ACCOUNT_MANAGEMENT")], "TRUE")
        self.assertEqual(values[("PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:DATA_USAGE_USER_CONTROL", "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL")], "TRUE")

    def test_public_deletion_page_is_available_without_login(self):
        response = self.client.get(reverse("public_account_deletion", args=[self.app.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "support@example.test")
        self.assertContains(response, "FREIRAUM")
