import json

from django.test import TestCase

from .models import Build, BuildAgent, Job, MobileApp, Release


class AgentCompletionStateTests(TestCase):
    def setUp(self):
        self.app = MobileApp.objects.create(
            name="State Test",
            slug="state-test",
            platform="ios",
            framework="other",
            status="active",
            bundle_id="de.example.state-test",
        )
        self.release = Release.objects.create(
            app=self.app,
            version_name="1.0.0",
            build_number=1,
            status="ready",
            auto_submit=False,
        )
        self.build = Build.objects.create(
            release=self.release,
            platform="ios",
            status="succeeded",
            artifact="builds/test.ipa",
            artifact_size=123,
            artifact_checksum="abc123",
            metadata={"sha256": "abc123", "xcode": "Xcode 26.6"},
        )
        self.agent, self.token = BuildAgent.create_with_token(
            name="test-mac",
            platform="macos",
            enabled=True,
        )

    def _complete(self, job, status, *, metadata=None, error=""):
        self.agent.current_job = job
        self.agent.save(update_fields=["current_job", "updated_at"])
        return self.client.post(
            f"/apps/agent-api/jobs/{job.pk}/complete/",
            data={
                "status": status,
                "metadata": json.dumps(metadata or {}),
                "error": error,
            },
            HTTP_X_AGENT_TOKEN=self.token,
            HTTP_X_AGENT_PLATFORM="macos",
        )

    def test_failed_app_store_upload_keeps_successful_ipa_build(self):
        job = Job.objects.create(
            app=self.app,
            release=self.release,
            build=self.build,
            type="upload_apple",
            status="running",
            available_to_agents=True,
            required_platform="macos",
        )

        response = self._complete(job, "failed", error="App Store record missing")

        self.assertEqual(response.status_code, 200)
        self.build.refresh_from_db()
        self.release.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(self.build.status, "succeeded")
        self.assertEqual(self.build.artifact.name, "builds/test.ipa")
        self.assertEqual(self.build.metadata["xcode"], "Xcode 26.6")
        self.assertEqual(self.release.status, "ready")
        self.assertEqual(job.status, "failed")

    def test_successful_app_store_upload_only_adds_store_metadata(self):
        job = Job.objects.create(
            app=self.app,
            release=self.release,
            build=self.build,
            type="upload_apple",
            status="running",
            available_to_agents=True,
            required_platform="macos",
        )

        response = self._complete(
            job,
            "succeeded",
            metadata={"external_build_id": "apple-build-123", "processing_state": "VALID"},
        )

        self.assertEqual(response.status_code, 200)
        self.build.refresh_from_db()
        self.release.refresh_from_db()
        self.assertEqual(self.build.status, "succeeded")
        self.assertEqual(self.build.external_build_id, "apple-build-123")
        self.assertEqual(self.build.metadata["xcode"], "Xcode 26.6")
        self.assertEqual(
            self.build.metadata["apple_upload"]["processing_state"],
            "VALID",
        )
        self.assertEqual(self.release.status, "uploaded")
