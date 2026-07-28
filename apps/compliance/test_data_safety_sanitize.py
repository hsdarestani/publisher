from __future__ import annotations

import csv
import io

from django.test import TestCase

from apps.publisher.models import MobileApp

from .data_safety_sanitize import clear_unselected_data_answers
from .services import get_or_create_profile


class DataSafetyConditionalSanitizerTests(TestCase):
    def setUp(self):
        app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-sanitize-test",
            platform="android",
            package_name="de.freiraum.parking",
        )
        self.profile = get_or_create_profile(app)
        self.profile.data_practices = {
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
            }
        }
        self.profile.save()

    def test_unselected_usage_rows_are_completely_blank_even_when_template_is_stale(self):
        source = io.StringIO()
        writer = csv.writer(source, lineterminator="\n")
        writer.writerow(
            [
                "Question ID (machine readable)",
                "Response ID (machine readable)",
                "Response value",
                "Answer requirement",
            ]
        )
        writer.writerows(
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

        output = clear_unselected_data_answers(source.getvalue(), self.profile)
        rows = list(csv.DictReader(io.StringIO(output)))
        by_pair = {
            (row["Question ID (machine readable)"], row["Response ID (machine readable)"]): row["Response value"]
            for row in rows
        }

        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_NAME:PSL_DATA_USAGE_EPHEMERAL", "")],
            "",
        )
        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_NAME:DATA_USAGE_USER_CONTROL", "PSL_DATA_USAGE_USER_CONTROL_OPTIONAL")],
            "",
        )
        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_EMAIL:PSL_DATA_USAGE_EPHEMERAL", "")],
            "FALSE",
        )
        self.assertEqual(
            by_pair[("PSL_DATA_USAGE_RESPONSES:PSL_PRECISE_LOCATION:PSL_DATA_USAGE_COLLECTION_AND_SHARING", "PSL_DATA_USAGE_ONLY_COLLECTED")],
            "TRUE",
        )
        self.assertEqual(by_pair[("PSL_DATA_TYPES_PERSONAL", "PSL_NAME")], "")
        self.assertEqual(by_pair[("PSL_DATA_TYPES_PERSONAL", "PSL_EMAIL")], "TRUE")

    def test_unknown_future_unselected_type_is_also_cleared(self):
        source = (
            "Question ID,Response ID,Response value\n"
            "PSL_DATA_USAGE_RESPONSES:PSL_FUTURE_BIOMETRIC:PSL_DATA_USAGE_EPHEMERAL,,FALSE\n"
        )
        output = clear_unselected_data_answers(source, self.profile)
        row = next(csv.DictReader(io.StringIO(output)))
        self.assertEqual(row["Response value"], "")
