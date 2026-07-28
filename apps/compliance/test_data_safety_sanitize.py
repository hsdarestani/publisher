from __future__ import annotations

import csv
import io

from django.test import TestCase

from apps.publisher.models import MobileApp

from .data_safety_sanitize import clear_unselected_data_answers
from .services import get_or_create_profile


HEADERS = [
    "Question ID (machine readable)",
    "Response ID (machine readable)",
    "Response value",
    "Answer requirement",
]


class DataSafetyConditionalSanitizerTests(TestCase):
    def setUp(self):
        app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-sanitize-test",
            platform="android",
            package_name="de.freiraum.parking",
        )
        self.profile = get_or_create_profile(app)
        self.profile.app_access = "unrestricted"
        self.profile.account_deletion = "not_applicable"
        self.profile.data_practices = {
            "account_creation": False,
            "deletion_request": False,
            "data_types": {
                "personal_info.email": {
                    "collected": True,
                    "shared": False,
                    "required": True,
                    "purposes": ["account_management"],
                },
                "location.precise": {
                    "collected": True,
                    "shared": False,
                    "required": False,
                    "purposes": ["app_functionality"],
                },
            },
        }
        self.profile.save()

    def _sanitize(self, rows):
        source = io.StringIO()
        writer = csv.writer(source, lineterminator="\n")
        writer.writerow(HEADERS)
        writer.writerows(rows)
        output = clear_unselected_data_answers(source.getvalue(), self.profile)
        return list(csv.DictReader(io.StringIO(output)))

    def test_unselected_usage_rows_are_completely_blank_even_when_template_is_stale(self):
        rows = self._sanitize(
            [
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_NAME:PSL_DATA_USAGE_EPHEMERAL",
                    "",
                    "FALSE",
                    "MAYBE_REQUIRED",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_NAME:DATA_USAGE_USER_CONTROL",
                    "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL",
                    "TRUE",
                    "SINGLE_CHOICE",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL",
                    "",
                    "FALSE",
                    "MAYBE_REQUIRED",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:PSL_DATA_USAGE_COLLECTION_AND_SHARING",
                    "PSL_DATA_USAGE_ONLY_COLLECTED",
                    "TRUE",
                    "MULTIPLE_CHOICE",
                ],
                ["PSL_DATA_TYPES_PERSONAL", "PSL_NAME", "TRUE", "MULTIPLE_CHOICE"],
                ["PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL", "TRUE", "MULTIPLE_CHOICE"],
            ]
        )
        by_pair = {
            (row[HEADERS[0]], row[HEADERS[1]]): row[HEADERS[2]]
            for row in rows
        }

        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_NAME:PSL_DATA_USAGE_EPHEMERAL", "")],
            "",
        )
        self.assertEqual(
            by_pair[
                (
                    "PSL_DATA_USAGE_RESPONSES:PSL_NAME:DATA_USAGE_USER_CONTROL",
                    "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL",
                )
            ],
            "",
        )
        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL", "")],
            "FALSE",
        )
        self.assertEqual(
            by_pair[
                (
                    "PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:PSL_DATA_USAGE_COLLECTION_AND_SHARING",
                    "PSL_DATA_USAGE_ONLY_COLLECTED",
                )
            ],
            "TRUE",
        )
        self.assertEqual(by_pair[("PSL_DATA_TYPES_PERSONAL", "PSL_NAME")], "")
        self.assertEqual(by_pair[("PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL")], "TRUE")

    def test_stored_but_inactive_data_type_is_not_selected(self):
        self.profile.data_practices["data_types"]["personal_info.name"] = {
            "collected": False,
            "shared": False,
            "required": False,
            "purposes": [],
        }
        self.profile.save(update_fields=["data_practices", "updated_at"])

        rows = self._sanitize(
            [
                ["PSL_DATA_TYPES_PERSONAL", "PSL_NAME", "TRUE", "MULTIPLE_CHOICE"],
                ["PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL", "TRUE", "MULTIPLE_CHOICE"],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_NAME:PSL_DATA_USAGE_EPHEMERAL",
                    "",
                    "FALSE",
                    "MAYBE_REQUIRED",
                ],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL",
                    "",
                    "FALSE",
                    "MAYBE_REQUIRED",
                ],
            ]
        )
        by_pair = {(row[HEADERS[0]], row[HEADERS[1]]): row[HEADERS[2]] for row in rows}
        self.assertEqual(by_pair[("PSL_DATA_TYPES_PERSONAL", "PSL_NAME")], "")
        self.assertEqual(by_pair[("PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL")], "TRUE")
        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_NAME:PSL_DATA_USAGE_EPHEMERAL", "")],
            "",
        )
        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL", "")],
            "FALSE",
        )

    def test_no_active_data_sets_top_level_no_and_blanks_all_usage(self):
        self.profile.data_practices["data_types"] = {
            "personal_info.email": {
                "collected": False,
                "shared": False,
                "required": False,
                "purposes": [],
            }
        }
        self.profile.save(update_fields=["data_practices", "updated_at"])

        rows = self._sanitize(
            [
                ["PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA", "", "TRUE", "REQUIRED"],
                ["PSL_DATA_COLLECTION", "PSL_YES", "TRUE", "SINGLE_CHOICE"],
                ["PSL_DATA_COLLECTION", "PSL_NO", "", "SINGLE_CHOICE"],
                ["PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL", "TRUE", "MULTIPLE_CHOICE"],
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL",
                    "",
                    "FALSE",
                    "MAYBE_REQUIRED",
                ],
            ]
        )
        by_pair = {(row[HEADERS[0]], row[HEADERS[1]]): row[HEADERS[2]] for row in rows}
        self.assertEqual(by_pair[("PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA", "")], "FALSE")
        self.assertEqual(by_pair[("PSL_DATA_COLLECTION", "PSL_YES")], "")
        self.assertEqual(by_pair[("PSL_DATA_COLLECTION", "PSL_NO")], "TRUE")
        self.assertEqual(by_pair[("PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL")], "")
        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL", "")],
            "",
        )

    def test_account_conditional_answers_are_blank_without_account_creation(self):
        rows = self._sanitize(
            [
                ["PSL_HAS_OUTSIDE_APP_ACCOUNTS", "", "FALSE", "MAYBE_REQUIRED"],
                ["PSL_ACCOUNT_DELETION_URL", "", "https://example.com/delete", "MAYBE_REQUIRED"],
                ["PSL_ACM_SPECIFY", "", "Email and password", "MAYBE_REQUIRED"],
                ["PSL_DATA_DELETION_URL", "", "https://example.com/delete-data", "MAYBE_REQUIRED"],
            ]
        )
        self.assertTrue(all(row[HEADERS[2]] == "" for row in rows))

    def test_unknown_future_unselected_type_is_also_cleared(self):
        rows = self._sanitize(
            [
                [
                    "PSL_DATA_USAGE_RESPONSES:PSL_FUTURE_BIOMETRIC:PSL_DATA_USAGE_EPHEMERAL",
                    "",
                    "FALSE",
                    "MAYBE_REQUIRED",
                ]
            ]
        )
        self.assertEqual(rows[0][HEADERS[2]], "")
