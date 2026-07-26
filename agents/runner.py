#!/usr/bin/env python3
"""A+ Publisher self-hosted build agent.

Run this on a Linux Android builder or a Mac with Xcode. The agent polls the
Publisher server, executes only jobs assigned to its token, streams logs, and
uploads the resulting AAB/IPA directly back to your own server.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse, urlunparse
import jwt
import requests

VERSION = "1.0.0"

class Agent:
    def __init__(self, server, token, interval=15, work_root=None):
        self.server = server.rstrip("/")
        self.token = token
        self.interval = interval
        self.work_root = Path(work_root or tempfile.gettempdir()) / "aplus-publisher-agent"
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"X-Agent-Token": token, "X-Agent-Hostname": socket.gethostname(), "X-Agent-Version": VERSION})

    def run(self):
        print(f"A+ Publisher Agent {VERSION} on {platform.system()} · {self.server}", flush=True)
        while True:
            try:
                response = self.session.post(f"{self.server}/apps/agent-api/claim/", timeout=45)
                response.raise_for_status()
                job = response.json().get("job")
                if not job:
                    time.sleep(self.interval); continue
                self.execute(job)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"poll error: {exc}", flush=True)
                time.sleep(min(self.interval * 2, 60))

    def execute(self, job):
        job_id, job_type, payload = job["id"], job["type"], job["payload"]
        workspace = self.work_root / f"job-{job_id}"
        shutil.rmtree(workspace, ignore_errors=True); workspace.mkdir(parents=True)
        metadata, artifact, error = {}, None, ""
        try:
            self.log(job_id, f"Claimed {job_type} on {socket.gethostname()}", 2)
            if job_type in {"build_android", "build_ios"}:
                artifact, metadata = self.build(job_id, job_type, payload, workspace)
            elif job_type == "upload_apple":
                metadata = self.upload_apple(job_id, payload, workspace)
            else:
                raise RuntimeError(f"Unsupported agent job type: {job_type}")
            self.complete(job_id, "succeeded", artifact, metadata, "")
        except Exception as exc:
            error = str(exc)
            self.log(job_id, f"FAILED: {error}", 95)
            self.complete(job_id, "failed", None, metadata, error)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def build(self, job_id, job_type, payload, workspace):
        repo_dir = workspace / "repo"
        repo_url = self.authenticated_url(payload["repository_url"], payload.get("repository_token", ""))
        branch = payload.get("branch") or "main"
        self.run_command(job_id, ["git", "clone", "--depth", "50", "--branch", branch, repo_url, str(repo_dir)], workspace, 8)
        if payload.get("commit"):
            self.run_command(job_id, ["git", "fetch", "--depth", "1", "origin", payload["commit"]], repo_dir, 12)
            self.run_command(job_id, ["git", "checkout", payload["commit"]], repo_dir, 14)
        config = payload.get("build_config") or {}
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (config.get("env") or {}).items()})
        env.update({"APP_VERSION_NAME": str(payload["version_name"]), "APP_BUILD_NUMBER": str(payload["build_number"])})
        if job_type == "build_android":
            command = config.get("android_command") or self.default_android_command(payload)
            pattern = config.get("android_artifact") or "**/*.aab"
        else:
            command = config.get("ios_command") or self.default_ios_command(payload)
            pattern = config.get("ios_artifact") or "**/*.ipa"
        self.run_shell(job_id, command, repo_dir, env, 20)
        files = [Path(p) for p in glob.glob(str(repo_dir / pattern), recursive=True) if Path(p).is_file()]
        if not files:
            raise RuntimeError(f"Build succeeded but no artifact matched: {pattern}")
        artifact = max(files, key=lambda p: p.stat().st_mtime)
        sha = self.sha256(artifact)
        self.log(job_id, f"Artifact: {artifact.relative_to(repo_dir)} ({artifact.stat().st_size} bytes)", 90)
        return artifact, {"sha256": sha, "commit": self.git_output(repo_dir, "rev-parse", "HEAD"), "agent": socket.gethostname()}

    @staticmethod
    def default_android_command(payload):
        framework = payload.get("framework")
        if framework == "flutter":
            return f"flutter pub get && flutter build appbundle --release --build-name {shlex.quote(str(payload['version_name']))} --build-number {int(payload['build_number'])}"
        if framework in {"react_native", "native"}:
            return "cd android && chmod +x gradlew && ./gradlew bundleRelease"
        raise RuntimeError("Set build_config.android_command for this framework.")

    @staticmethod
    def default_ios_command(payload):
        if payload.get("framework") == "flutter":
            return f"flutter pub get && flutter build ipa --release --build-name {shlex.quote(str(payload['version_name']))} --build-number {int(payload['build_number'])}"
        raise RuntimeError("Set build_config.ios_command and ios_artifact for native or React Native iOS builds.")

    def upload_apple(self, job_id, payload, workspace):
        apple = payload.get("apple") or {}
        for key in ("issuer_id", "key_id", "private_key"):
            if not apple.get(key): raise RuntimeError(f"Missing Apple credential: {key}")
        artifact_url = payload.get("artifact_url")
        if not artifact_url: raise RuntimeError("iOS artifact URL is missing.")
        if artifact_url.startswith("/"): artifact_url = self.server + artifact_url
        ipa = workspace / "app.ipa"
        with self.session.get(artifact_url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with ipa.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024): handle.write(chunk)
        key_dir = Path.home() / ".appstoreconnect" / "private_keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        key_path = key_dir / f"AuthKey_{apple['key_id']}.p8"
        key_path.write_text(apple["private_key"]); key_path.chmod(0o600)
        try:
            command = ["xcrun", "iTMSTransporter", "-m", "upload", "-assetFile", str(ipa), "-apiKey", apple["key_id"], "-apiIssuer", apple["issuer_id"]]
            self.run_command(job_id, command, workspace, 25, redact=[apple["key_id"], apple["issuer_id"]])
            build = self.wait_for_apple_build(payload, apple, job_id)
            return {"external_build_id": build["id"], "processing_state": build.get("attributes", {}).get("processingState"), "uploaded_at": datetime.now(timezone.utc).isoformat()}
        finally:
            key_path.unlink(missing_ok=True)

    def wait_for_apple_build(self, payload, apple, job_id, timeout=1800):
        token = self.apple_token(apple)
        headers = {"Authorization": f"Bearer {token}"}
        bundle = payload.get("bundle_id")
        app_resp = requests.get(f"https://api.appstoreconnect.apple.com/v1/apps", params={"filter[bundleId]": bundle, "limit": 1}, headers=headers, timeout=60)
        app_resp.raise_for_status(); apps = app_resp.json().get("data", [])
        if not apps: raise RuntimeError(f"App Store app record not found for {bundle}")
        app_id = apps[0]["id"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            token = self.apple_token(apple); headers["Authorization"] = f"Bearer {token}"
            response = requests.get("https://api.appstoreconnect.apple.com/v1/builds", params={"filter[app]": app_id, "filter[version]": str(payload["build_number"]), "sort": "-uploadedDate", "limit": 10}, headers=headers, timeout=60)
            response.raise_for_status()
            for build in response.json().get("data", []):
                state = build.get("attributes", {}).get("processingState")
                self.log(job_id, f"Apple processing state: {state}", 80)
                if state == "VALID": return build
                if state in {"FAILED", "INVALID"}: raise RuntimeError(f"Apple build processing failed: {state}")
            time.sleep(30)
        raise RuntimeError("Timed out waiting for App Store build processing.")

    @staticmethod
    def apple_token(apple):
        now = datetime.now(timezone.utc)
        return jwt.encode({"iss": apple["issuer_id"], "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=19)).timestamp()), "aud": "appstoreconnect-v1"}, apple["private_key"], algorithm="ES256", headers={"kid": apple["key_id"]})

    def run_shell(self, job_id, command, cwd, env, progress):
        self.log(job_id, f"$ {command}", progress)
        process = subprocess.Popen(command, cwd=cwd, env=env, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            self.log(job_id, line.rstrip(), min(progress + 50, 88))
        code = process.wait()
        if code: raise RuntimeError(f"Command failed with exit code {code}")

    def run_command(self, job_id, command, cwd, progress, redact=None):
        display = " ".join(shlex.quote(str(x)) for x in command)
        for value in redact or []: display = display.replace(value, "***")
        self.log(job_id, f"$ {display}", progress)
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout: self.log(job_id, line.rstrip(), min(progress + 50, 88))
        code = process.wait()
        if code: raise RuntimeError(f"Command failed with exit code {code}")

    def log(self, job_id, line, progress):
        line = line[-8000:]
        try:
            self.session.post(f"{self.server}/apps/agent-api/jobs/{job_id}/log/", json={"line": line, "progress": progress}, timeout=30).raise_for_status()
        except Exception as exc:
            print(f"log delivery failed: {exc}", flush=True)
        print(line, flush=True)

    def complete(self, job_id, status, artifact, metadata, error):
        data = {"status": status, "metadata": json.dumps(metadata), "error": error}
        files = None
        handle = None
        try:
            if artifact:
                handle = artifact.open("rb"); files = {"artifact": (artifact.name, handle, "application/octet-stream")}
            response = self.session.post(f"{self.server}/apps/agent-api/jobs/{job_id}/complete/", data=data, files=files, timeout=600)
            response.raise_for_status()
        finally:
            if handle: handle.close()

    @staticmethod
    def authenticated_url(url, token):
        if not token: return url
        parsed = urlparse(url)
        if parsed.hostname != "github.com": return url
        return urlunparse((parsed.scheme or "https", f"x-access-token:{quote(token, safe='')}@{parsed.netloc}", parsed.path, parsed.params, parsed.query, parsed.fragment))

    @staticmethod
    def git_output(cwd, *args):
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()

    @staticmethod
    def sha256(path):
        import hashlib
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""): h.update(chunk)
        return h.hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=os.getenv("PUBLISHER_URL"))
    parser.add_argument("--token", default=os.getenv("PUBLISHER_AGENT_TOKEN"))
    parser.add_argument("--interval", type=int, default=int(os.getenv("PUBLISHER_POLL_INTERVAL", "15")))
    parser.add_argument("--work-root", default=os.getenv("PUBLISHER_WORK_ROOT"))
    args = parser.parse_args()
    if not args.server or not args.token: parser.error("--server and --token are required (or set PUBLISHER_URL/PUBLISHER_AGENT_TOKEN).")
    Agent(args.server, args.token, args.interval, args.work_root).run()

if __name__ == "__main__": main()
