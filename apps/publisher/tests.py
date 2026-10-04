import os
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from .github_actions import wake_cloud_agent
from .models import MobileApp, AppLocalization, Release, Build, BuildAgent, Job, StoreAccount, Submission
from .readiness import evaluate_release
from .tasks import handle_submit_google


class PublisherTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "test", email="owner@example.com", password="pass12345"
        )
        self.client.login(username="test", password="pass12345")
        self.app = MobileApp.objects.create(
            name="Test App",
            slug="test-app",
            package_name="com.test.app",
            bundle_id="com.test.app",
            privacy_policy_url="https://example.com/privacy",
            support_url="https://example.com/support",
        )
        AppLocalization.objects.create(
            app=self.app,
            locale="en-US",
            title="Test App",
            full_description="A complete app description",
        )
        self.release = Release.objects.create(
            app=self.app, version_name="1.0.0", build_number=1
        )
        Build.objects.create(release=self.release, platform="android", status="succeeded")
        Build.objects.create(release=self.release, platform="ios", status="succeeded")


    def test_automation_release_requires_token_and_queues_platform_jobs(self):
        url = reverse("automation_release")
        payload = {
            "app_identifier": self.app.bundle_id,
            "version_name": "1.2.3",
            "build_number": 23,
            "platforms": ["android", "ios"],
            "android_track": "internal",
            "auto_submit": False,
            "release_notes": "Automated build",
            "source_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        }
        with patch.dict(os.environ, {"PUBLISHER_AUTOMATION_TOKEN": "automation-test-token"}):
            unauthorized = self.client.post(
                url,
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(unauthorized.status_code, 401)

            response = self.client.post(
                url,
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer automation-test-token",
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual({x["platform"] for x in data["queued"]}, {"android", "ios"})
        release = Release.objects.get(app=self.app, version_name="1.2.3", build_number=23)
        self.assertEqual(release.source_commit, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(
            set(release.jobs.filter(status="queued").values_list("type", flat=True)),
            {"build_android", "build_ios"},
        )


    @patch("apps.publisher.signals.wake_cloud_agent")
    def test_automation_bootstraps_be_different(self, wake):
        url = reverse("automation_release")
        MobileApp.objects.filter(slug="be-different").delete()
        payload = {
            "app_identifier": "com.smarbiz.bedifferent",
            "version_name": "1.0.0",
            "build_number": 1,
            "platforms": ["android", "ios"],
            "source_branch": "main",
            "source_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        }
        with patch.dict(os.environ, {"PUBLISHER_AUTOMATION_TOKEN": "automation-test-token"}):
            response = self.client.post(
                url,
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer automation-test-token",
            )
        self.assertEqual(response.status_code, 200)
        app = MobileApp.objects.get(slug="be-different")
        self.assertEqual(app.package_name, "com.smarbiz.bedifferent")
        self.assertEqual(app.bundle_id, "com.smarbiz.bedifferent")
        self.assertEqual(app.framework, "react_native")
        self.assertEqual(app.build_config["android_command"], "bash mobile/scripts/build-android.sh")
        self.assertEqual(app.build_config["ios_command"], "bash mobile/scripts/build-ios.sh")
        release = Release.objects.get(app=app, version_name="1.0.0", build_number=1)
        self.assertEqual(set(release.jobs.values_list("type", flat=True)), {"build_android", "build_ios"})

    def test_dashboard_and_app_pages(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(self.app.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.release.get_absolute_url()).status_code, 200)

    def test_login_accepts_full_email_address(self):
        self.client.logout()
        self.assertTrue(
            self.client.login(username="owner@example.com", password="pass12345")
        )

    def test_readiness_reports_missing_assets_without_crashing(self):
        result = evaluate_release(self.release)
        self.assertFalse(result["ready"])
        self.assertGreater(result["errors"], 0)
        self.assertTrue(any(c["key"] == "android-icon" for c in result["checks"]))

    def test_store_account_credentials_are_encrypted(self):
        account = StoreAccount(provider="google", name="A+")
        account.set_credentials({"client_email": "x@example.com", "private_key": "secret"})
        account.save()
        self.assertNotIn("secret", account.credential_blob)
        self.assertEqual(account.get_credentials()["private_key"], "secret")

    @patch("apps.publisher.tasks.handle_upload_google")
    def test_submit_google_is_idempotent_after_successful_upload(self, upload):
        submission = Submission.objects.create(
            app=self.app,
            release=self.release,
            platform="android",
            state="in_review",
            external_id="1",
        )
        job = Job.objects.create(
            type="submit_google",
            app=self.app,
            release=self.release,
            build=self.release.builds.get(platform="android"),
        )

        result = handle_submit_google(job)

        self.assertEqual(result["submission_id"], submission.pk)
        self.assertTrue(result["already_submitted"])
        upload.assert_not_called()

    def test_agent_claim(self):
        agent, token = BuildAgent.create_with_token(name="linux-1", platform="linux")
        # Bootstrap migrations may leave historical queued jobs in the test DB.
        # Isolate this assertion and verify agent work is claimed FIFO.
        Job.objects.filter(
            status="queued",
            available_to_agents=True,
            required_platform="linux",
        ).update(status="failed")
        older = Job.objects.create(
            type="build_android",
            app=self.app,
            release=self.release,
            build=self.release.builds.get(platform="android"),
            available_to_agents=True,
            required_platform="linux",
        )
        newer = Job.objects.create(
            type="build_android",
            app=self.app,
            release=self.release,
            build=self.release.builds.get(platform="android"),
            available_to_agents=True,
            required_platform="linux",
        )
        response = self.client.post(reverse("agent_claim"), HTTP_X_AGENT_TOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job"]["id"], older.pk)
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(older.status, "running")
        self.assertEqual(newer.status, "queued")

    @patch("apps.publisher.signals.wake_cloud_agent")
    def test_queued_agent_job_wakes_matching_cloud_runner(self, wake):
        with self.captureOnCommitCallbacks(execute=True):
            Job.objects.create(
                type="build_android",
                app=self.app,
                release=self.release,
                build=self.release.builds.get(platform="android"),
                available_to_agents=True,
                required_platform="linux",
            )
        wake.assert_called_once_with("linux")

    @override_settings(
        PUBLISHER_GITHUB_TOKEN="test-token",
        PUBLISHER_GITHUB_REPOSITORY="hsdarestani/publisher",
        PUBLISHER_GITHUB_REF="main",
    )
    @patch("apps.publisher.github_actions.requests.post")
    def test_cloud_runner_dispatch_uses_github_workflow_api(self, post):
        post.return_value.status_code = 204
        self.assertTrue(wake_cloud_agent("linux"))
        post.assert_called_once()
        self.assertIn("cloud-linux.yml/dispatches", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["json"], {"ref": "main"})

    @override_settings(PUBLISHER_GITHUB_TOKEN="")
    @patch("apps.publisher.github_actions.requests.post")
    def test_missing_dispatch_token_is_a_safe_noop(self, post):
        self.assertFalse(wake_cloud_agent("linux"))
        post.assert_not_called()

    @patch("apps.publisher.cloud_auth.jwt.decode")
    @patch("apps.publisher.cloud_auth._GITHUB_JWKS.get_signing_key_from_jwt")
    def test_github_oidc_cloud_mac_can_claim_ios_job(self, signing_key, decode):
        signing_key.return_value = SimpleNamespace(key=object())
        decode.return_value = {
            "repository": "hsdarestani/publisher",
            "ref": "refs/heads/main",
            "event_name": "schedule",
            "exp": 9999999999,
            "iat": 1,
            "iss": "https://token.actions.githubusercontent.com",
            "aud": "https://publisher.smarbiz.sbs",
        }
        build = self.release.builds.get(platform="ios")
        job = Job.objects.create(
            type="build_ios",
            app=self.app,
            release=self.release,
            build=build,
            available_to_agents=True,
            required_platform="macos",
        )
        response = self.client.post(
            reverse("agent_claim"), HTTP_X_GITHUB_OIDC="signed-token"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job"]["id"], job.pk)
        self.assertTrue(BuildAgent.objects.filter(platform="macos").exists())

    def test_missing_agent_token_is_rejected(self):
        response = self.client.post(reverse("agent_claim"))
        self.assertEqual(response.status_code, 401)
