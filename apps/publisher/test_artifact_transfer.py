import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from .models import Build, BuildAgent, Job, MobileApp, Release


class AgentChunkedArtifactTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.app = MobileApp.objects.create(
            name="A+ Test", slug="a-test-chunks", platform="ios",
            framework="other", status="active", bundle_id="de.test.chunks",
        )
        self.release = Release.objects.create(
            app=self.app, version_name="1.0.31", build_number=67, auto_submit=False,
        )
        self.build = Build.objects.create(
            release=self.release, platform="ios", status="running",
        )
        self.job = Job.objects.create(
            app=self.app, release=self.release, build=self.build,
            type="build_ios", status="running", available_to_agents=True,
            required_platform="macos",
        )
        self.agent, self.token = BuildAgent.create_with_token(
            name="mac-test-chunks", platform="macos", enabled=True,
        )
        self.agent.current_job = self.job
        self.agent.save(update_fields=["current_job", "updated_at"])

    def _send(self, data, index, total, full_size, sha):
        return self.client.post(
            f"/apps/agent-api/jobs/{self.job.pk}/artifact-chunk/",
            data=data,
            content_type="application/octet-stream",
            HTTP_X_AGENT_TOKEN=self.token,
            HTTP_X_AGENT_PLATFORM="macos",
            HTTP_X_ARTIFACT_INDEX=str(index),
            HTTP_X_ARTIFACT_TOTAL=str(total),
            HTTP_X_ARTIFACT_SIZE=str(full_size),
            HTTP_X_ARTIFACT_SHA256=sha,
        )

    def _complete(self, metadata=None):
        return self.client.post(
            f"/apps/agent-api/jobs/{self.job.pk}/complete/",
            data={
                "status": "succeeded",
                "metadata": json.dumps(metadata or {}),
                "error": "",
            },
            HTTP_X_AGENT_TOKEN=self.token,
            HTTP_X_AGENT_PLATFORM="macos",
        )

    def test_upload_then_finalise_then_replay_is_idempotent(self):
        data = b"signed-ipa-test\0" * 800
        sha = hashlib.sha256(data).hexdigest()
        first = self._send(data, 0, 1, len(data), sha)
        self.assertEqual(first.status_code, 200)
        duplicate = self._send(data, 0, 1, len(data), sha)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["already_received"])
        metadata = {
            "sha256": sha, "artifact_transfer": "chunked",
            "artifact_size": len(data), "artifact_name": "App.ipa",
        }
        response = self._complete(metadata)
        self.assertEqual(response.status_code, 200, response.content)
        self.build.refresh_from_db()
        self.job.refresh_from_db()
        self.release.refresh_from_db()
        self.assertEqual(self.build.status, "succeeded")
        self.assertTrue(self.build.artifact)
        self.assertEqual(self.build.artifact_size, len(data))
        self.assertEqual(self.build.artifact_checksum, sha)
        self.assertEqual(self.job.status, "succeeded")
        self.assertEqual(self.release.status, "ready")
        with self.build.artifact.open("rb") as file:
            self.assertEqual(file.read(), data)
        replay = self._complete(metadata)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["already_completed"])

    def test_missing_or_corrupt_chunks_cannot_record_success(self):
        data = b"build output"
        sha = hashlib.sha256(data).hexdigest()
        meta = {"sha256": sha, "artifact_transfer": "chunked",
                "artifact_size": len(data), "artifact_name": "App.ipa"}
        missing = self._complete(meta)
        self.assertEqual(missing.status_code, 422)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "running")
        self.assertEqual(self._send(b"WRONG OUTPUT", 0, 1, len(data), sha).status_code, 400)
        self.assertEqual(self._send(b"wrong output", 0, 1, len(data), sha).status_code, 200)
        mismatch = self._complete(meta)
        self.assertEqual(mismatch.status_code, 422)
        self.build.refresh_from_db()
        self.assertFalse(self.build.artifact)
        self.assertNotEqual(self.build.status, "succeeded")

    def test_success_without_artifact_is_rejected(self):
        response = self._complete()
        self.assertEqual(response.status_code, 422)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "running")

    def test_chunks_require_correct_agent_and_running_job(self):
        data = b"abc"
        digest = hashlib.sha256(data).hexdigest()
        result = self.client.post(
            f"/apps/agent-api/jobs/{self.job.pk}/artifact-chunk/",
            data=data, content_type="application/octet-stream",
            HTTP_X_ARTIFACT_INDEX="0", HTTP_X_ARTIFACT_TOTAL="1",
            HTTP_X_ARTIFACT_SIZE="3", HTTP_X_ARTIFACT_SHA256=digest,
        )
        self.assertEqual(result.status_code, 401)
