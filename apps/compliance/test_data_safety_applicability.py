from __future__ import annotations

import csv
import io

from django.test import TestCase

from apps.publisher.models import MobileApp

from .data_safety_applicability import enforce_conditional_applicability
from .services import get_or_create_profile


HEADERS = [
    "Question ID (machine readable)",
    "Response ID (machine readable)",
    "Response value",
    "Answer requirement",
]


class DataSafetyApplicabilityRegressionTests(TestCase):
    def setUp(self):
        self.app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-applicability-regression",
            platform="android",
            package_name="de.freiraum.parking",
            requires_login=True,
        )
        self.profile = get_or_create_profile(self.app)
        self.profile.app_access = "login"
        self.profile.account_deletion = "support"
        self.profile.data_practices = {
            "account_creation": True,
            "data_types": {
                "personal_info.email": {
                    "collected": True,
                    "shared": False,
                    "required": True,
                    "purposes": ["account_management"],
                },
                "user_ids": {
                    "collected": False,
                    "shared": True,
                    "required": False,
                    "purposes": ["app_functionality"],
                },
            },
        }
        self.profile.save()

    def _finalize(self, rows):
        source = io.StringIO()
        writer = csv.writer(source, lineterminator="\n")
        writer.writerow(HEADERS)
        writer.writerows(rows)
        output = enforce_conditional_applicability(source.getvalue(), self.profile)
        return list(csv.DictReader(io.StringIO(output)))

    def test_outside_app_accounts_is_blank_without_explicit_evidence(self):
        rows = self._finalize(
            [
                [
                    "PSL_HAS_OUTSIDE_APP_ACCOUNTS",
                    "",
                    "FALSE",
                    "MAYBE_REQUIRED",
                ]
            ]
        )
        self.assertEqual(rows[0][HEADERS[2]], "")

    def test_outside_app_accounts_can_be_answered_with_explicit_evidence(self):
        self.profile.data_practices["outside_app_accounts"] = False
        self.profile.save(update_fields=["data_practices", "updated_at"])
        rows = self._finalize(
            [["PSL_HAS_OUTSIDE_APP_ACCOUNTS", "", "TRUE", "MAYBE_REQUIRED"]]
        )
        self.assertEqual(rows[0][HEADERS[2]], "FALSE")

    def test_email_sharing_purpose_is_blank_when_email_is_not_shared(self):
        rows = self._finalize(
            [
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_SHARING_PURPOSE",
                    "PSL_ACCOUNT_MANAGEMENT",
                    "TRUE",
                    "MULTIPLE_CHOICE",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:DATA_USAGE_COLLECTION_PURPOSE",
                    "PSL_ACCOUNT_MANAGEMENT",
                    "TRUE",
                    "MULTIPLE_CHOICE",
                ],
            ]
        )
        self.assertEqual(rows[0][HEADERS[2]], "")
        self.assertEqual(rows[1][HEADERS[2]], "TRUE")

    def test_collection_purpose_is_blank_when_type_is_only_shared(self):
        rows = self._finalize(
            [
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_USER_ACCOUNT:DATA_USAGE_COLLECTION_PURPOSE",
                    "PSL_APP_FUNCTIONALITY",
                    "TRUE",
                    "MULTIPLE_CHOICE",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_USER_ACCOUNT:DATA_USAGE_SHARING_PURPOSE",
                    "PSL_APP_FUNCTIONALITY",
                    "TRUE",
                    "MULTIPLE_CHOICE",
                ],
            ]
        )
        self.assertEqual(rows[0][HEADERS[2]], "")
        self.assertEqual(rows[1][HEADERS[2]], "TRUE")
