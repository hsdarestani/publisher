from types import SimpleNamespace

from django.test import SimpleTestCase

from .store_compliance import (
    apple_age_rating_profile,
    apple_content_rights_declaration,
    apple_uses_non_exempt_encryption,
)


class AppleStoreComplianceTests(SimpleTestCase):
    def setUp(self):
        self.a_studio = SimpleNamespace(slug="a-studio")
        self.unknown = SimpleNamespace(slug="unknown")

    def test_a_studio_declares_only_exempt_encryption(self):
        self.assertIs(apple_uses_non_exempt_encryption(self.a_studio), False)

    def test_a_studio_declares_third_party_content_rights(self):
        self.assertEqual(
            apple_content_rights_declaration(self.a_studio),
            "USES_THIRD_PARTY_CONTENT",
        )

    def test_a_studio_age_profile_matches_product_capabilities(self):
        profile = apple_age_rating_profile(self.a_studio)

        self.assertIs(profile["userGeneratedContent"], True)
        self.assertIs(profile["messagingAndChat"], False)
        self.assertIs(profile["socialMedia"], False)
        self.assertIs(profile["unrestrictedWebAccess"], False)
        self.assertIs(profile["advertising"], False)
        self.assertIs(profile["gambling"], False)
        self.assertIs(profile["lootBox"], False)
        self.assertEqual(profile["profanityOrCrudeHumor"], "NONE")
        self.assertEqual(profile["sexualContentOrNudity"], "NONE")
        self.assertEqual(profile["violenceRealistic"], "NONE")
        self.assertIsNone(profile["kidsAgeBand"])

    def test_profile_is_returned_as_a_copy(self):
        first = apple_age_rating_profile(self.a_studio)
        first["advertising"] = True
        second = apple_age_rating_profile(self.a_studio)
        self.assertIs(second["advertising"], False)

    def test_unknown_app_has_no_implicit_compliance_answers(self):
        self.assertIsNone(apple_uses_non_exempt_encryption(self.unknown))
        self.assertIsNone(apple_content_rights_declaration(self.unknown))
        self.assertIsNone(apple_age_rating_profile(self.unknown))
