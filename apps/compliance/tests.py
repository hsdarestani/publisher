from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.publisher.models import AppLocalization, MobileApp, StoreAccount

from .services import apply_google_apis, fill_data_safety_template, generate_pack, get_or_create_profile, issue_companion_token


@override_settings(PUBLIC_URL="https://publisher.example.test")
class ComplianceAutomationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pass12345",
        )
        self.client = Client()
        self.client.login(username="owner", password="pass12345")
        self.app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-test",
            client_name="A+ Solution GmbH",
            platform="android",
            framework="flutter",
            package_name="de.freiraum.parking",
            repository_url="https://github.com/hsdarestani/parkplatz.git",
            default_branch="main",
            requires_login=True,
            review_username="reviewer@example.com",
            review_notes="Use the supplied account to review booking and parking management.",
            support_url="https://example.com/support",
        )
        self.app.set_review_password("review-secret")
        self.app.save(update_fields=["review_password_blob", "updated_at"])
        AppLocalization.objects.create(
            app=self.app,
            locale="de-DE",
            title="FREIRAUM",
            short_description="Parkplätze finden und reservieren.",
            full_description="FREIRAUM hilft Nutzern, Parkplätze zu finden, zu reservieren und anzubieten.",
        )

    def evidence(self):
        return {
            "pubspec.yaml": """
name: freiraum
dependencies:
  flutter:
    sdk: flutter
  geolocator: ^14.0.2
  file_picker: ^10.3.10
""",
            "android/app/src/main/AndroidManifest.xml": """
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <uses-permission android:name="android.permission.INTERNET" />
  <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
  <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
</manifest>
""",
            "README.md": "Users sign in, select a vehicle, find a parking location and create a booking.",
        }

    @patch("apps.compliance.services.generate_compliance_pack", return_value=(None, ""))
    @patch("apps.compliance.services.GitHubRepoClient.evidence_files")
    def test_rule_engine_generates_full_policy_pack_without_openai(self, evidence_files, ai):
        evidence_files.return_value = self.evidence()
        profile = get_or_create_profile(self.app)
        pack = generate_pack(profile)
        profile.refresh_from_db()

        self.assertFalse(profile.ai_used)
        self.assertIn(profile.status, {"ready", "needs_review"})
        self.assertEqual(profile.app_access, "login")
        self.assertFalse(profile.has_ads)
        self.assertIn("location.precise", profile.data_practices["data_types"])
        self.assertIn("location.approximate", profile.data_practices["data_types"])
        self.assertIn("files.documents", profile.data_practices["data_types"])
        self.assertIn("Datenschutzerklärung", profile.privacy_policy_text)
        self.assertEqual(profile.console_autofill["app_access"]["password"], "review-secret")
        refreshed_app = self.app.__class__.objects.get(pk=self.app.pk)
        self.assertTrue(refreshed_app.privacy_policy_url.startswith("https://publisher.example.test/"))
        self.assertIn("store_listing", pack)

    @patch("apps.compliance.services.generate_compliance_pack", return_value=(None, ""))
    @patch("apps.compliance.services.GitHubRepoClient.evidence_files")
    def test_ad_sdk_is_never_overridden_to_no_ads(self, evidence_files, ai):
        evidence = self.evidence()
        evidence["pubspec.yaml"] += "\n  google_mobile_ads: ^5.0.0\n"
        evidence_files.return_value = evidence
        profile = get_or_create_profile(self.app)
        generate_pack(profile)
        profile.refresh_from_db()
        self.assertTrue(profile.has_ads)
        self.assertTrue(profile.store_declarations["contains_ads"])

    def test_current_google_csv_template_is_filled_from_generated_practices(self):
        profile = get_or_create_profile(self.app)
        profile.data_practices = {
            "encrypted_in_transit": True,
            "deletion_request": True,
            "data_types": {
                "location.precise": {
                    "label": "Precise location",
                    "collected": True,
                    "shared": False,
                    "required": False,
                    "purposes": ["app_functionality"],
                }
            },
        }
        template = (
            "Question ID,Question,Answer,Response value\n"
            "Q1,Does your app collect or share any required user data types?,Yes,\n"
            "Q1,Does your app collect or share any required user data types?,No,\n"
            "Q2,Is all of the user data collected by your app encrypted in transit?,Yes,\n"
            "Q3,Can users request that their data is deleted?,Yes,\n"
            "Q4,Precise location collected,Collected,\n"
            "Q5,Precise location shared,Shared,\n"
        )
        profile.data_safety_template = SimpleUploadedFile(
            "data-safety.csv",
            template.encode("utf-8"),
            content_type="text/csv",
        )
        profile.save()

        output = fill_data_safety_template(profile)
        self.assertIn("Q1,Does your app collect or share any required user data types?,Yes,TRUE", output)
        self.assertIn("Q1,Does your app collect or share any required user data types?,No,FALSE", output)
        self.assertIn("Q2,Is all of the user data collected by your app encrypted in transit?,Yes,TRUE", output)
        self.assertIn("Q4,Precise location collected,Collected,TRUE", output)
        self.assertIn("Q5,Precise location shared,Shared,FALSE", output)

    def test_short_lived_companion_payload_is_public_only_with_token(self):
        profile = get_or_create_profile(self.app)
        profile.console_autofill = {"ads": {"contains_ads": False}, "app": {"name": "FREIRAUM"}}
        profile.save(update_fields=["console_autofill", "updated_at"])
        token = issue_companion_token(profile)

        response = self.client.get(reverse("compliance_companion_payload", args=[token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response.json()["app"]["name"], "FREIRAUM")

        profile.companion_token_expires_at = timezone.now() - timedelta(seconds=1)
        profile.save(update_fields=["companion_token_expires_at", "updated_at"])
        expired = self.client.get(reverse("compliance_companion_payload", args=[token]))
        self.assertEqual(expired.status_code, 410)

    def test_compliance_dashboard_and_hosted_privacy_policy(self):
        profile = get_or_create_profile(self.app)
        profile.privacy_policy_text = "Datenschutzerklärung für FREIRAUM"
        profile.save(update_fields=["privacy_policy_text", "updated_at"])

        dashboard = self.client.get(reverse("compliance_detail", args=[self.app.pk]))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Compliance pipeline")

        privacy = self.client.get(reverse("public_privacy_policy", args=[self.app.slug]))
        self.assertEqual(privacy.status_code, 200)
        self.assertContains(privacy, "Datenschutzerklärung für FREIRAUM")

    @patch("apps.compliance.services.GooglePlayClient")
    def test_apply_uses_official_listing_and_data_safety_apis(self, client_class):
        account = StoreAccount(provider="google", name="A+ Google")
        account.set_credentials({"client_email": "publisher@example.iam.gserviceaccount.com", "private_key": "private"})
        account.save()
        self.app.google_account = account
        self.app.save(update_fields=["google_account", "updated_at"])
        profile = get_or_create_profile(self.app)
        profile.data_safety_csv = "Question ID,Response value\nQ1,TRUE\n"
        profile.save(update_fields=["data_safety_csv", "updated_at"])

        api = Mock()
        api.apply_store_content.return_value = {"warnings": [], "localizations": 1, "images": 0}
        api.apply_data_safety.return_value = {"ok": True}
        client_class.return_value = api

        result = apply_google_apis(profile)
        api.apply_store_content.assert_called_once()
        api.apply_data_safety.assert_called_once_with("de.freiraum.parking", profile.data_safety_csv)
        self.assertIn("Store listing and images", result.applied)
        self.assertIn("Data safety", result.applied)
        self.assertTrue(any("App access" in item for item in result.skipped))

    def test_extension_archive_is_downloadable(self):
        response = self.client.get(reverse("compliance_companion_extension"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("a-plus-play-console-companion.zip", response["Content-Disposition"])
