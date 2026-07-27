from __future__ import annotations

import base64
import re

import requests
from django.conf import settings

from .base import IntegrationError


class GitHubRepoClient:
    def __init__(self, repository_url, token=""):
        self.repository_url = repository_url
        self.owner, self.repo = self._parse(repository_url)
        self.last_error = ""
        self.auth_source = "anonymous"

        global_token = getattr(settings, "PUBLISHER_GITHUB_TOKEN", "") or ""
        tokens = []
        for candidate in (token, global_token, ""):
            candidate = (candidate or "").strip()
            if candidate not in tokens:
                tokens.append(candidate)
        self._tokens = tokens
        self.token = tokens[0] if tokens else ""
        self.headers = self._headers(self.token)

    @staticmethod
    def _parse(url):
        match = re.search(r"github\.com[/:]([^/]+)/([^/.]+)(?:\.git)?$", url.rstrip("/"))
        if not match:
            raise IntegrationError("Only GitHub repository URLs are supported for repository sync.")
        return match.group(1), match.group(2)

    @staticmethod
    def _headers(token=""):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get(self, path, params=None):
        last_response = None
        for index, token in enumerate(self._tokens):
            headers = self._headers(token)
            response = requests.get(
                f"https://api.github.com/repos/{self.owner}/{self.repo}{path}",
                headers=headers,
                params=params,
                timeout=45,
            )
            if response.ok:
                self.token = token
                self.headers = headers
                self.auth_source = "repository token" if index == 0 and token else "global token" if token else "anonymous"
                self.last_error = ""
                return response.json()

            last_response = response
            # An expired per-app token, a token without repository access, or a
            # private-repository 404 may still succeed with the global Publisher
            # token. Public repositories can also be retried anonymously.
            if response.status_code in {401, 403, 404} and index < len(self._tokens) - 1:
                continue
            break

        status = getattr(last_response, "status_code", "unknown")
        text = getattr(last_response, "text", "No response")
        self.last_error = f"GitHub API {status}: {text[:500]}"
        raise IntegrationError(self.last_error)

    def commits(self, branch="main", limit=30):
        return self._get("/commits", {"sha": branch, "per_page": min(limit, 100)})

    def tree(self, branch="main"):
        return self._get(f"/git/trees/{branch}", {"recursive": "1"}).get("tree", [])

    def file_text(self, path: str, branch="main", max_bytes=250_000) -> str:
        """Read a repository text file without cloning the whole project."""
        data = self._get(f"/contents/{path}", {"ref": branch})
        if data.get("type") != "file":
            return ""
        if int(data.get("size") or 0) > max_bytes:
            return ""
        content = data.get("content", "")
        if data.get("encoding") == "base64" and content:
            raw = base64.b64decode(content)
            return raw.decode("utf-8", errors="replace")
        download_url = data.get("download_url")
        if not download_url:
            return ""
        response = requests.get(download_url, headers=self.headers, timeout=45)
        if not response.ok or len(response.content) > max_bytes:
            return ""
        return response.text

    def evidence_files(self, branch="main", paths=None):
        """Return source evidence without making compliance generation brittle.

        Repository access enriches the compliance result, but an expired token or
        a temporary GitHub outage must not prevent policy generation from the app's
        stored metadata. Repository sync remains strict through ``sync_summary``.
        """
        paths = paths or [
            "README.md",
            "pubspec.yaml",
            "package.json",
            "android/app/src/main/AndroidManifest.xml",
            "android/app/build.gradle",
            "android/app/build.gradle.kts",
            "ios/Runner/Info.plist",
        ]
        try:
            available = {item.get("path") for item in self.tree(branch) if item.get("type") == "blob"}
        except IntegrationError:
            return {}

        result = {}
        for path in paths:
            if path not in available:
                continue
            try:
                text = self.file_text(path, branch)
            except Exception as exc:
                self.last_error = str(exc)
                continue
            if text:
                result[path] = text
        return result

    def sync_summary(self, branch="main"):
        commits = self.commits(branch, 30)
        tree = self.tree(branch)
        paths = [x.get("path", "") for x in tree]
        stack = self.detect_stack(paths)
        latest = commits[0] if commits else {}
        return {
            "stack": stack,
            "latest_sha": latest.get("sha", ""),
            "latest_date": latest.get("commit", {}).get("committer", {}).get("date"),
            "commits": [
                {
                    "sha": c.get("sha", "")[:8],
                    "message": c.get("commit", {}).get("message", "").splitlines()[0],
                    "author": c.get("commit", {}).get("author", {}).get("name", ""),
                    "date": c.get("commit", {}).get("author", {}).get("date"),
                }
                for c in commits
            ],
        }

    @staticmethod
    def detect_stack(paths):
        rules = [
            ("Flutter", lambda p: "pubspec.yaml" in p),
            ("React Native", lambda p: "package.json" in p and any(x.startswith("android/") for x in p)),
            ("Django", lambda p: any(x.endswith("manage.py") for x in p)),
            ("Laravel", lambda p: "artisan" in p),
            ("Android/Gradle", lambda p: any(x.endswith(("build.gradle", "build.gradle.kts")) for x in p)),
            ("iOS/Xcode", lambda p: any(".xcodeproj/" in x or ".xcworkspace/" in x for x in p)),
            ("Docker", lambda p: any(x.endswith("Dockerfile") or "docker-compose" in x for x in p)),
            ("Node.js", lambda p: "package.json" in p),
        ]
        return [name for name, check in rules if check(paths)]
