#!/usr/bin/env python3
"""Linux/Android agent for A+ Publisher.

The same implementation supports two modes:
- Ephemeral GitHub-hosted execution using short-lived OIDC authentication.
- A persistent Docker agent using a server-generated static agent token.
"""
from __future__ import annotations

import base64
import glob
import os
from pathlib import Path
import shlex
import subprocess
import time

from cloud_macos import CloudMacAgent
from runner import Agent


class CloudLinuxAgent(CloudMacAgent):
    def __init__(self, server: str, max_jobs: int = 3):
        static_token = os.getenv("PUBLISHER_AGENT_TOKEN", "").strip()
        self.continuous = bool(static_token) or os.getenv("PUBLISHER_CONTINUOUS", "") == "1"
        if static_token:
            Agent.__init__(
                self,
                server,
                token=static_token,
                interval=int(os.getenv("PUBLISHER_POLL_INTERVAL", "5")),
                work_root=os.getenv("PUBLISHER_WORK_ROOT"),
            )
            self.max_jobs = max_jobs
        else:
            super().__init__(server, max_jobs=max_jobs)
        self.session.headers["X-Agent-Platform"] = "linux"

    def run(self):
        mode = "persistent" if self.continuous else "ephemeral"
        print(f"A+ Cloud Linux ({mode}) connected to {self.server}", flush=True)
        processed = 0
        had_failures = False
        while self.continuous or processed < self.max_jobs:
            try:
                response = self.session.post(f"{self.server}/apps/agent-api/claim/", timeout=45)
                response.raise_for_status()
                job = response.json().get("job")
                if not job:
                    if self.continuous:
                        time.sleep(self.interval)
                        continue
                    print("No Android job is queued.", flush=True)
                    break

                if job["type"] == "build_android":
                    try:
                        signing_response = self.session.get(
                            f"{self.server}/signing/jobs/{job['id']}/credentials/",
                            timeout=90,
                        )
                        if not signing_response.ok:
                            detail = signing_response.text.strip()[:2000]
                            raise RuntimeError(
                                f"Publisher signing endpoint returned HTTP {signing_response.status_code}: {detail}"
                            )
                        signing_payload = signing_response.json()
                        job["payload"]["android_signing"] = signing_payload["android_signing"]
                        job["payload"]["android_certificate_sha256"] = signing_payload.get(
                            "certificate_sha256", ""
                        )
                    except Exception as exc:
                        error = f"Android signing setup failed: {exc}"
                        self.log(job["id"], f"FAILED: {error}", 95)
                        self.complete(job["id"], "failed", None, {}, error)
                        had_failures = True
                        processed += 1
                        continue

                if self.execute(job) is False:
                    had_failures = True
                processed += 1
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                if not self.continuous:
                    raise
                print(f"persistent agent poll error: {exc}", flush=True)
                time.sleep(min(self.interval * 2, 60))

        if had_failures and not self.continuous:
            raise RuntimeError("One or more Android jobs failed. See the Publisher execution log.")

    def build(self, job_id, job_type, payload, workspace):
        if job_type != "build_android":
            return super().build(job_id, job_type, payload, workspace)

        repo_dir = workspace / "repo"
        self._clone(job_id, payload, workspace, repo_dir)
        if payload.get("commit"):
            self._run(job_id, ["git", "fetch", "--depth", "1", "origin", payload["commit"]], repo_dir, 12)
            self._run(job_id, ["git", "checkout", payload["commit"]], repo_dir, 14)

        signing = payload.get("android_signing") or {}
        missing = [
            key
            for key in ("keystore_base64", "key_alias", "store_password", "key_password")
            if not signing.get(key)
        ]
        if missing:
            raise RuntimeError("Android upload signing is incomplete: " + ", ".join(missing))

        android_dir = repo_dir / "android"
        android_dir.mkdir(parents=True, exist_ok=True)
        key_path = android_dir / "upload-keystore.jks"
        properties_path = android_dir / "key.properties"
        key_path.write_bytes(base64.b64decode(signing["keystore_base64"]))
        key_path.chmod(0o600)
        properties_path.write_text(
            "\n".join(
                [
                    f"storePassword={signing['store_password']}",
                    f"keyPassword={signing['key_password']}",
                    f"keyAlias={signing['key_alias']}",
                    "storeFile=../upload-keystore.jks",
                    "",
                ]
            )
        )
        properties_path.chmod(0o600)

        config = payload.get("build_config") or {}
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in (config.get("env") or {}).items()})
        env.update(
            {
                "APP_VERSION_NAME": str(payload["version_name"]),
                "APP_BUILD_NUMBER": str(payload["build_number"]),
            }
        )

        if config.get("android_command"):
            command = config["android_command"]
        elif payload.get("framework") == "flutter":
            command_parts = [
                "flutter pub get",
                "flutter build appbundle --release",
                f"--build-name {shlex.quote(str(payload['version_name']))}",
                f"--build-number {int(payload['build_number'])}",
            ]
            for key, value in (config.get("android_dart_defines") or {}).items():
                command_parts.append(
                    "--dart-define=" + shlex.quote(f"{key}={value}")
                )
            command = " && ".join(command_parts[:1]) + " && " + " ".join(command_parts[1:])
        else:
            command = self.default_android_command(payload)

        try:
            self.run_shell(job_id, command, repo_dir, env, 20)
            pattern = config.get("android_artifact") or "build/app/outputs/bundle/release/*.aab"
            files = [
                Path(path)
                for path in glob.glob(str(repo_dir / pattern), recursive=True)
                if Path(path).is_file()
            ]
            if not files:
                raise RuntimeError(f"Build completed but no AAB matched: {pattern}")
            artifact = max(files, key=lambda path: path.stat().st_mtime)
            self._run(job_id, ["jarsigner", "-verify", "-verbose", "-certs", str(artifact)], repo_dir, 86)
            self.log(job_id, f"Signed AAB ready: {artifact.relative_to(repo_dir)}", 92)
            return artifact, {
                "sha256": self.sha256(artifact),
                "commit": self.git_output(repo_dir, "rev-parse", "HEAD"),
                "agent": "A+ Persistent Linux" if self.continuous else "A+ Cloud Linux · GitHub Actions",
                "android_certificate_sha256": payload.get("android_certificate_sha256", ""),
                "java": subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0],
                "flutter": subprocess.check_output(["flutter", "--version"], text=True).splitlines()[0],
            }
        finally:
            properties_path.unlink(missing_ok=True)
            key_path.unlink(missing_ok=True)


def main():
    server = os.getenv("PUBLISHER_URL", "https://publisher.smarbiz.sbs")
    max_jobs = int(os.getenv("PUBLISHER_MAX_JOBS", "3"))
    CloudLinuxAgent(server, max_jobs=max_jobs).run()


if __name__ == "__main__":
    main()
