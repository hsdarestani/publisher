from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.publisher.models import MobileApp

from .forms import ComplianceProfileForm
from .models import ComplianceProfile
from .signals import (
    ACCOUNT_DELETION_QUESTION,
    ACCOUNT_DELETION_REQUIRED,
    PAYMENT_QUESTION,
)


class ComplianceReviewConfirmationTests(TestCase):
    def setUp(self):
        self.app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-review-test",
            platform="android",
            framework="flutter",
            package_name="de.freiraum.parking.review",
            requires_login=True,
        )
        self.profile = ComplianceProfile.objects.create(
            app=self.app,
            status="needs_review",
            app_access="login",
            last_generated_at=timezone.now(),
            unresolved_questions=[ACCOUNT_DELETION_QUESTION, PAYMENT_QUESTION],
            data_practices={
                "account_creation": True,
                "deletion_request": False,
                "data_types": {
                    "financial_info.purchase_history": {
                        "label": "Purchase history",
                        "collected": True,
                        "shared": False,
                        "purposes": ["app_functionality"],
                    }
                },
            },
        )

    def test_confirmed_support_deletion_and_external_payment_make_profile_ready(self):
        self.profile.account_deletion = "support"
        self.profile.payment_handling = "external"
        self.profile.payment_details = "Stripe Checkout; card data never reaches the app or our backend."
        self.profile.save()
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.status, "ready")
        self.assertEqual(self.profile.unresolved_questions, [])
        self.assertTrue(self.profile.data_practices["deletion_request"])
        self.assertEqual(self.profile.data_practices["account_deletion_method"], "support")
        self.assertFalse(self.profile.data_practices["payment_handling"]["payment_data_collected"])
        self.assertTrue(self.profile.data_practices["payment_handling"]["external_processor"])

    def test_missing_deletion_path_remains_blocking_for_login_app(self):
        self.profile.account_deletion = "unavailable"
        self.profile.payment_handling = "none"
        self.profile.save()
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.status, "needs_review")
        self.assertIn(ACCOUNT_DELETION_REQUIRED, self.profile.unresolved_questions)
        self.assertNotIn(PAYMENT_QUESTION, self.profile.unresolved_questions)

    def test_direct_payment_requires_details(self):
        form = ComplianceProfileForm(
            data={
                "primary_locale": "de-DE",
                "support_email": "support@example.com",
                "purpose": "Parking bookings",
                "business_model": "marketplace",
                "has_ads": False,
                "target_age_groups": ["18 and over"],
                "app_access": "login",
                "app_access_instructions": "Use reviewer credentials.",
                "account_deletion": "support",
                "account_deletion_url": "",
                "payment_handling": "direct",
                "payment_details": "",
            },
            instance=self.profile,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("payment_details", form.errors)

    def test_web_deletion_requires_public_url(self):
        form = ComplianceProfileForm(
            data={
                "primary_locale": "de-DE",
                "support_email": "support@example.com",
                "purpose": "Parking bookings",
                "business_model": "marketplace",
                "has_ads": False,
                "target_age_groups": ["18 and over"],
                "app_access": "login",
                "app_access_instructions": "Use reviewer credentials.",
                "account_deletion": "web",
                "account_deletion_url": "",
                "payment_handling": "none",
                "payment_details": "",
            },
            instance=self.profile,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("account_deletion_url", form.errors)
