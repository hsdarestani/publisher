from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .job_recovery import recover_stale_internal_jobs
from .models import Build, Job, MobileApp, Release


class StaleInternalJobRecoveryTests(TestCase):
    def setUp(self):
        self.app = MobileApp.objects.create(
            name="A+ Studio Test",
            slug="a-studio-test",
            platform="both",
            framework="other",
            status="active",
        )
        self.release = Release.objects.create(
            app=self.app,
            version_name="1.0.0",
            build_number=1,
        )
        self.ios = Build.objects.create(
            release=self.release,
            platform="ios",
            status="succeeded",
            artifact="builds/test.ipa",
        )

    def _job(self, job_type, *, minutes_old, available_to_agents=False):
        job = Job.objects.create(
            app=self.app,
            release=self.release,
            build=self.ios,
            type=job_type,
            status="running",
            available_to_agents=available_to_agents,
            required_platform="macos" if available_to_agents else "",
        )
        Job.objects.filter(pk=job.pk).update(
            started_at=timezone.now() - timedelta(minutes=minutes_old)
        )
        job.refresh_from_db()
        return job

    def test_stale_internal_submit_is_failed_for_safe_retry(self):
        stale = self._job("submit_apple", minutes_old=30)

        recovered = recover_stale_internal_jobs(
            app=self.app,
            release=self.release,
            job_types={"submit_apple"},
            stale_after_minutes=15,
        )

        self.assertEqual(recovered, [stale.pk])
        stale.refresh_from_db()
        self.assertEqual(stale.status, "failed")
        self.assertIsNotNone(stale.finished_at)
        self.assertIn("worker restart", stale.error)
        self.assertIn("safe to retry", stale.logs)

    def test_recent_internal_submit_is_not_touched(self):
        recent = self._job("submit_apple", minutes_old=5)

        recovered = recover_stale_internal_jobs(
            app=self.app,
            release=self.release,
            job_types={"submit_apple"},
            stale_after_minutes=15,
        )

        self.assertEqual(recovered, [])
        recent.refresh_from_db()
        self.assertEqual(recent.status, "running")

    def test_agent_owned_upload_is_never_recovered(self):
        upload = self._job(
            "upload_apple",
            minutes_old=60,
            available_to_agents=True,
        )

        with self.assertRaises(ValueError):
            recover_stale_internal_jobs(
                app=self.app,
                release=self.release,
                job_types={"upload_apple"},
                stale_after_minutes=15,
            )

        upload.refresh_from_db()
        self.assertEqual(upload.status, "running")

    def test_other_release_is_not_touched(self):
        other_release = Release.objects.create(
            app=self.app,
            version_name="2.0.0",
            build_number=2,
        )
        other_build = Build.objects.create(
            release=other_release,
            platform="ios",
            status="succeeded",
        )
        job = Job.objects.create(
            app=self.app,
            release=other_release,
            build=other_build,
            type="submit_apple",
            status="running",
            available_to_agents=False,
        )
        Job.objects.filter(pk=job.pk).update(
            started_at=timezone.now() - timedelta(minutes=60)
        )

        recovered = recover_stale_internal_jobs(
            app=self.app,
            release=self.release,
            job_types={"submit_apple"},
            stale_after_minutes=15,
        )

        self.assertEqual(recovered, [])
        job.refresh_from_db()
        self.assertEqual(job.status, "running")
