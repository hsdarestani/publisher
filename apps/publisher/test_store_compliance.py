from types import SimpleNamespace

from django.test import SimpleTestCase

from .store_compliance import apple_uses_non_exempt_encryption


class AppleExportComplianceTests(SimpleTestCase):
    def test_a_studio_declares_only_exempt_encryption(self):
        self.assertIs(
            apple_uses_non_exempt_encryption(SimpleNamespace(slug="a-studio")),
            False,
        )

    def test_unknown_app_has_no_implicit_compliance_answer(self):
        self.assertIsNone(
            apple_uses_non_exempt_encryption(SimpleNamespace(slug="unknown"))
        )
