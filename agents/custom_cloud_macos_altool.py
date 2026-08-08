#!/usr/bin/env python3
"""Cloud Mac runner with Publisher signing plus modern App Store upload.

Xcode 26 no longer executes the bundled iTMSTransporter stub for uploads.
Apple continues to support `xcrun altool --upload-app` for App Store Connect,
including team App Store Connect API key authentication. Keep the .p8 file only
for the duration of the upload job and reuse the existing build-processing poll.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from custom_cloud_macos import CustomBuildMacAgent


class AltoolCloudMacAgent(CustomBuildMacAgent):
    def upload_apple(self, job_id, payload, workspace):
        apple = payload.get("apple") or {}
        for key in ("issuer_id", "key_id", "private_key"):
            if not apple.get(key):
                raise RuntimeError(f"Missing Apple credential: {key}")

        artifact_url = payload.get("artifact_url")
        if not artifact_url:
            raise RuntimeError("iOS artifact URL is missing.")
        if artifact_url.startswith("/"):
            artifact_url = self.server + artifact_url

        ipa = Path(workspace) / "app.ipa"
        with self.session.get(artifact_url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with ipa.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    handle.write(chunk)

        key_dir = Path.home() / ".appstoreconnect" / "private_keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        key_path = key_dir / f"AuthKey_{apple['key_id']}.p8"
        key_path.write_text(apple["private_key"])
        key_path.chmod(0o600)

        try:
            self.log(job_id, "Uploading IPA to App Store Connect with Xcode altool.", 20)
            command = [
                "xcrun", "altool",
                "--upload-app",
                "-f", str(ipa),
                "-t", "ios",
                "--apiKey", apple["key_id"],
                "--apiIssuer", apple["issuer_id"],
            ]
            self.run_command(
                job_id,
                command,
                workspace,
                25,
                redact=[apple["key_id"], apple["issuer_id"]],
            )
            self.log(job_id, "Apple accepted the binary upload; waiting for App Store processing.", 72)
            build = self.wait_for_apple_build(payload, apple, job_id)
            return {
                "external_build_id": build["id"],
                "processing_state": build.get("attributes", {}).get("processingState"),
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "upload_tool": "xcrun altool",
            }
        finally:
            key_path.unlink(missing_ok=True)


def main():
    server = os.getenv("PUBLISHER_URL", "https://publisher.smarbiz.sbs")
    max_jobs = int(os.getenv("PUBLISHER_MAX_JOBS", "3"))
    AltoolCloudMacAgent(server, max_jobs=max_jobs).run()


if __name__ == "__main__":
    main()
