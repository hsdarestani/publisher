from __future__ import annotations

import json
from unittest.mock import Mock, patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.integrations.base import IntegrationError
from apps.integrations.google_play_cloud import is_google_edge_blocked, make_cloud_token
from apps.publisher.models import AppLocalization, MobileApp
from scripts.google_play_cloud_operation import apply_payload, download_asset

from .models import ComplianceRun
from .services import get_or_create_profile
from .tasks import execute_compliance_run


@override_settings(
    PUBLIC_URL="https://publisher.example.test",
    PUBLISHER_GITHUB_TOKEN="github-token",
    PUBLISHER_GITHUB_REPOSITORY="hsdarestani/publisher",
    PUBLISHER_GITHUB_REF="main",
)
class GooglePlayCloudFallbackTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.app = MobileApp.objects.create(
            name="FREIRAUM",
            slug="freiraum-cloud-test",
            platform="android",
            package_name="de.freiraum.parking",
        )
        AppLocalization.objects.create(
            app=self.app,
            locale="de-DE",
            title="FREIRAUM",
            short_description="Parkplätze finden.",
            full_description="Parkplätze finden und reservieren.",
        )
        self.profile = get_or_create_profile(self.app)

    @staticmethod
    def edge_error():
        error = IntegrationError("Google edge blocked the request")
        error.diagnostics = {
            "endpoint_probes": [
                {"endpoint": "androidpublisher.googleapis.com", "status": 403, "content_type": "text/html"},
                {"endpoint": "www.googleapis.com legacy", "status": 403, "content_type": "text/html"},
            ]
        }
        return error

    def test_edge_block_detection_requires_html_403_on_every_endpoint(self):
        self.assertTrue(is_google_edge_blocked(self.edge_error()))
        other = IntegrationError("permission denied")
        other.diagnostics = {
            "endpoint_probes": [
                {"endpoint": "androidpublisher.googleapis.com", "status": 403, "content_type": "application/json"}
            ]
        }
        self.assertFalse(is_google_edge_blocked(other))

    @patch("apps.compliance.tasks.dispatch_google_play_cloud")
    @patch("apps.compliance.tasks.apply_google_apis")
    def test_apply_run_dispatches_cloud_fallback_instead_of_failing(self, apply_google, dispatch):
        apply_google.side_effect = self.edge_error()
        dispatch.return_value = Mock(as_dict=lambda: {"workflow": "google-play-cloud-operation.yml"})
        run = ComplianceRun.objects.create(profile=self.profile, action="apply")

        execute_compliance_run.run(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, "running")
        self.assertEqual(run.progress, 50)
        self.assertEqual(run.result["execution"], "github-actions")
        self.assertEqual(run.result["state"], "dispatched")
        dispatch.assert_called_once_with(run.pk)

    def test_signed_cloud_payload_and_success_callback_finalize_run(self):
        self.profile.data_safety_csv = ""
        self.profile.save(update_fields=["data_safety_csv", "updated_at"])
        run = ComplianceRun.objects.create(profile=self.profile, action="apply", status="running", progress=50)
        token = make_cloud_token(run.pk)

        payload = self.client.get(
            reverse("compliance_google_cloud_payload", args=[run.pk]),
            {"token": token},
        )
        self.assertEqual(payload.status_code, 200)
        self.assertEqual(payload.json()["package_name"], "de.freiraum.parking")
        self.assertEqual(payload.json()["localizations"][0]["locale"], "de-DE")
        self.assertEqual(payload["Cache-Control"], "no-store")

        callback = self.client.post(
            reverse("compliance_google_cloud_callback", args=[run.pk]) + f"?token={token}",
            data=json.dumps(
                {
                    "success": True,
                    "executor": "github-actions",
                    "listing_count": 1,
                    "image_count": 0,
                    "data_safety_applied": False,
                    "warnings": [],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(callback.status_code, 200)
        run.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(run.status, "partial")
        self.assertEqual(run.progress, 100)
        self.assertEqual(run.result["execution"], "github-actions")
        self.assertEqual(self.profile.status, "partially_applied")

    def test_cloud_endpoints_reject_invalid_token(self):
        run = ComplianceRun.objects.create(profile=self.profile, action="apply", status="running")
        payload = self.client.get(
            reverse("compliance_google_cloud_payload", args=[run.pk]),
            {"token": "invalid"},
        )
        callback = self.client.post(
            reverse("compliance_google_cloud_callback", args=[run.pk]) + "?token=invalid",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(payload.status_code, 403)
        self.assertEqual(callback.status_code, 403)

    @patch("scripts.google_play_cloud_operation.requests.get")
    def test_binary_asset_download_does_not_attempt_json_parsing(self, get):
        response = Mock(ok=True, status_code=200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"})
        get.return_value = response
        asset = download_asset({"url": "https://publisher.example.test/media/icon.png", "name": "icon.png"})
        self.assertEqual(asset["content"], b"\x89PNG\r\n")
        self.assertEqual(asset["content_type"], "image/png")
        response.json.assert_not_called()

    @patch("scripts.google_play_cloud_operation.create_edit")
    @patch("scripts.google_play_cloud_operation.download_asset")
    def test_asset_preflight_failure_happens_before_google_edit(self, download, create_edit):
        download.side_effect = RuntimeError("asset unavailable")
        payload = {
            "package_name": "de.freiraum.parking",
            "localizations": [],
            "assets": [
                {
                    "locale": "de-DE",
                    "image_type": "icon",
                    "url": "https://publisher.example.test/media/icon.png",
                }
            ],
        }
        with self.assertRaisesMessage(RuntimeError, "asset unavailable"):
            apply_payload(payload, Mock())
        create_edit.assert_not_called()
