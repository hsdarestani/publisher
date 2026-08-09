from types import SimpleNamespace

from django.test import SimpleTestCase

from .review_contacts import apple_review_contact


class AppleReviewContactTests(SimpleTestCase):
    def test_a_studio_has_complete_review_contact(self):
        contact = apple_review_contact(SimpleNamespace(slug="a-studio"))

        self.assertEqual(contact["contactFirstName"], "Ashkan")
        self.assertEqual(contact["contactLastName"], "Asadian")
        self.assertEqual(contact["contactPhone"], "+491727779721")
        self.assertEqual(contact["contactEmail"], "info@aplus-solution.de")

    def test_unknown_app_does_not_invent_contact(self):
        self.assertEqual(apple_review_contact(SimpleNamespace(slug="unknown")), {})
