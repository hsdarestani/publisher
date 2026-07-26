#!/usr/bin/env python3
"""Ephemeral GitHub-hosted macOS agent for A+ Publisher.

GitHub provisions the Mac and Xcode. The workflow authenticates to Publisher
with a short-lived GitHub OIDC token, so no permanent build-agent secret is
required. Apple credentials are fetched only after a job is claimed and remain
inside the temporary runner for the duration of that job.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote

import jwt
import requests

from runner import Agent


class GitHubOIDCProvider:
    def __init__(self, audience: str):
        self.audience = audience.rstrip("/")
        self.value = ""
        self.exp = 0

    def token(self) -> str:
        now = int(time.time())
        if self.value and self.exp - now > 120:
            return self.value

        url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
        request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
        if not url or not request_token:
            raise RuntimeError("GitHub Actions OIDC environment is unavailable.")
        separator = "&" if "?" in url else "?"
        response = requests.get(
            f"{url}{separator}audience={quote(self.audience, safe='')}",
            headers={"Authorization": f"Bearer {request_token}"},
            timeout=30,
        )
        response.raise_for_status()
        self.value = response.json()["value"]
        claims = jwt.decode(self.value, options={"verify_signature": False, "verify_exp": False})
        self.exp = int(claims.get("exp", now + 300))
        return self.value


class GitHubOIDCAuth(requests.auth.AuthBase):
    def __init__(self, provider: GitHubOIDCProvider):
        self.provider = provider

    def __call__(self, request):
        request.headers["X-GitHub-OIDC"] = self.provider.token()
        return request


class CloudMacAgent(Agent):
    def __init__(self, server: str, max_jobs: int = 3):
        super().__init__(server, token="oidc-placeholder", interval=5)
        self.session.headers.pop("X-Agent-Token", None)
        self.session.headers["X-Agent-Platform"] = "macos"
        self.session.auth = GitHubOIDCAuth(GitHubOIDCProvider(server))
        self.max_jobs = max_jobs

    def run(self):
        print(f"A+ Cloud Mac connected to {self.server}", flush=True)
        processed = 0
        while processed < self.max_jobs:
            response = self.session.post(f"{self.server}/apps/agent-api/claim/", timeout=45)
            response.raise_for_status()
            job = response.json().get("job")
            if not job:
                print("No macOS job is queued.", flush=True)
                return
            self.execute(job)
            processed += 1

    def _run(self, job_id, command, cwd, progress, env=None, redact=None):
        display = " ".join(shlex.quote(str(value)) for value in command)
        for value in redact or []:
            display = display.replace(str(value), "***")
        self.log(job_id, f"$ {display}", progress)
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self.log(job_id, line.rstrip(), min(progress + 45, 88))
        code = process.wait()
        if code:
            raise RuntimeError(f"Command failed with exit code {code}")

    def _clone(self, job_id, payload, workspace, repo_dir):
        repository_url = payload["repository_url"]
        repository_token = payload.get("repository_token", "")
        branch = payload.get("branch") or "main"
        env = os.environ.copy()
        askpass = None
        if repository_token and "github.com" in repository_url:
            askpass = workspace / "git-askpass.sh"
            askpass.write_text(
                '#!/bin/sh\ncase "$1" in\n'
                '  *Username*) printf "%s" "x-access-token" ;;\n'
                '  *) printf "%s" "$APLUS_GIT_TOKEN" ;;\n'
                'esac\n'
            )
            askpass.chmod(0o700)
            env["GIT_ASKPASS"] = str(askpass)
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["APLUS_GIT_TOKEN"] = repository_token
        self._run(
            job_id,
            ["git", "clone", "--depth", "50", "--branch", branch, repository_url, str(repo_dir)],
            workspace,
            8,
            env=env,
        )
        if askpass:
            askpass.unlink(missing_ok=True)

    def _ensure_flutter(self, job_id, env):
        flutter_home = Path.home() / ".cache" / "aplus-publisher" / "flutter"
        flutter = flutter_home / "bin" / "flutter"
        if not flutter.exists():
            flutter_home.parent.mkdir(parents=True, exist_ok=True)
            self.log(job_id, "Installing the official Flutter stable SDK on the temporary cloud Mac.", 11)
            self._run(
                job_id,
                ["git", "clone", "--depth", "1", "--branch", "stable", "https://github.com/flutter/flutter.git", str(flutter_home)],
                flutter_home.parent,
                11,
            )
        env["PATH"] = f"{flutter_home / 'bin'}:{env.get('PATH', '')}"
        self._run(job_id, [str(flutter), "config", "--no-analytics"], flutter_home, 13, env=env)
        self._run(job_id, [str(flutter), "precache", "--ios"], flutter_home, 15, env=env)

    def build(self, job_id, job_type, payload, workspace):
        if job_type != "build_ios":
            return super().build(job_id, job_type, payload, workspace)

        repo_dir = workspace / "repo"
        self._clone(job_id, payload, workspace, repo_dir)
        if payload.get("commit"):
            self._run(job_id, ["git", "fetch", "--depth", "1", "origin", payload["commit"]], repo_dir, 12)
            self._run(job_id, ["git", "checkout", payload["commit"]], repo_dir, 14)

        config = payload.get("build_config") or {}
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in (config.get("env") or {}).items()})
        env.update({
            "APP_VERSION_NAME": str(payload["version_name"]),
            "APP_BUILD_NUMBER": str(payload["build_number"]),
        })

        if config.get("ios_command"):
            self.run_shell(job_id, config["ios_command"], repo_dir, env, 20)
            pattern = config.get("ios_artifact") or "**/*.ipa"
        elif payload.get("framework") == "flutter":
            self._ensure_flutter(job_id, env)
            self._build_flutter_ipa(job_id, payload, config, repo_dir, workspace, env)
            pattern = config.get("ios_artifact") or "build/ios/export/*.ipa"
        else:
            raise RuntimeError("Set build_config.ios_command and ios_artifact for this iOS project.")

        files = [Path(path) for path in glob.glob(str(repo_dir / pattern), recursive=True) if Path(path).is_file()]
        if not files:
            raise RuntimeError(f"Build completed but no IPA matched: {pattern}")
        artifact = max(files, key=lambda path: path.stat().st_mtime)
        self.log(job_id, f"IPA ready: {artifact.relative_to(repo_dir)}", 90)
        return artifact, {
            "sha256": self.sha256(artifact),
            "commit": self.git_output(repo_dir, "rev-parse", "HEAD"),
            "agent": "A+ Cloud Mac · GitHub Actions",
            "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True).strip(),
        }

    def _build_flutter_ipa(self, job_id, payload, config, repo_dir, workspace, env):
        apple = payload.get("apple") or {}
        missing = [key for key in ("issuer_id", "key_id", "private_key", "team_id") if not apple.get(key)]
        if missing:
            raise RuntimeError("Cloud signing needs Apple Team API credentials: " + ", ".join(missing))

        key_path = workspace / f"AuthKey_{apple['key_id']}.p8"
        key_path.write_text(apple["private_key"])
        key_path.chmod(0o600)
        archive_path = repo_dir / "build" / "ios" / "archive" / "Runner.xcarchive"
        export_path = repo_dir / "build" / "ios" / "export"
        export_options = workspace / "ExportOptions.plist"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.mkdir(parents=True, exist_ok=True)

        with export_options.open("wb") as handle:
            plistlib.dump({
                "method": config.get("ios_export_method", "app-store-connect"),
                "signingStyle": "automatic",
                "teamID": apple["team_id"],
                "destination": "export",
                "manageAppVersionAndBuildNumber": False,
                "stripSwiftSymbols": True,
                "uploadSymbols": True,
            }, handle)

        try:
            self._run(job_id, ["flutter", "pub", "get"], repo_dir, 18, env=env)
            self._run(job_id, [
                "flutter", "build", "ios", "--release", "--no-codesign",
                "--build-name", str(payload["version_name"]),
                "--build-number", str(payload["build_number"]),
            ], repo_dir, 24, env=env)

            workspace_path = repo_dir / config.get("ios_workspace", "ios/Runner.xcworkspace")
            project_path = repo_dir / config.get("ios_project", "ios/Runner.xcodeproj")
            source = ["-workspace", str(workspace_path)] if workspace_path.exists() else ["-project", str(project_path)]
            auth = [
                "-allowProvisioningUpdates",
                "-authenticationKeyPath", str(key_path),
                "-authenticationKeyID", apple["key_id"],
                "-authenticationKeyIssuerID", apple["issuer_id"],
            ]
            self._run(job_id, [
                "xcodebuild", *source,
                "-scheme", config.get("ios_scheme", "Runner"),
                "-configuration", config.get("ios_configuration", "Release"),
                "-destination", "generic/platform=iOS",
                "-archivePath", str(archive_path),
                "archive", *auth,
                f"DEVELOPMENT_TEAM={apple['team_id']}",
                "CODE_SIGN_STYLE=Automatic",
                f"MARKETING_VERSION={payload['version_name']}",
                f"CURRENT_PROJECT_VERSION={payload['build_number']}",
            ], repo_dir, 40, env=env, redact=[apple["key_id"], apple["issuer_id"]])
            self._run(job_id, [
                "xcodebuild", "-exportArchive",
                "-archivePath", str(archive_path),
                "-exportPath", str(export_path),
                "-exportOptionsPlist", str(export_options),
                *auth,
            ], repo_dir, 70, env=env, redact=[apple["key_id"], apple["issuer_id"]])
        finally:
            key_path.unlink(missing_ok=True)


def main():
    server = os.getenv("PUBLISHER_URL", "https://publisher.smarbiz.sbs")
    max_jobs = int(os.getenv("PUBLISHER_MAX_JOBS", "3"))
    CloudMacAgent(server, max_jobs=max_jobs).run()


if __name__ == "__main__":
    main()
