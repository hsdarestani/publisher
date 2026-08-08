#!/usr/bin/env python3
"""Cloud Mac wrapper that exposes short-lived Apple signing data to custom builds.

Custom iOS commands (Capacitor, native, React Native, etc.) receive only job-scoped
environment variables. The App Store Connect private key is written to the
runner's temporary workspace, chmod 0600, and removed immediately after build.
Nothing is persisted in the application repository or build_config.
"""
from __future__ import annotations

import os
from pathlib import Path

from cloud_macos import CloudMacAgent


class CustomBuildMacAgent(CloudMacAgent):
    def build(self, job_id, job_type, payload, workspace):
        config = payload.get("build_config") or {}
        if job_type != "build_ios" or not config.get("ios_command"):
            return super().build(job_id, job_type, payload, workspace)

        apple = payload.get("apple") or {}
        missing = [key for key in ("issuer_id", "key_id", "private_key", "team_id") if not apple.get(key)]
        if missing:
            raise RuntimeError("iOS custom-build signing needs Apple credentials: " + ", ".join(missing))

        workspace = Path(workspace)
        key_path = workspace / f"AuthKey_{apple['key_id']}.p8"
        key_path.write_text(apple["private_key"])
        key_path.chmod(0o600)

        payload = dict(payload)
        config = dict(config)
        custom_env = dict(config.get("env") or {})
        custom_env.update(
            {
                "APPLE_API_KEY_PATH": str(key_path),
                "APPLE_KEY_ID": apple["key_id"],
                "APPLE_ISSUER_ID": apple["issuer_id"],
                "IOS_TEAM_ID": apple["team_id"],
                "IOS_BUNDLE_ID": str(payload.get("bundle_id") or ""),
            }
        )
        config["env"] = custom_env
        payload["build_config"] = config

        try:
            return super().build(job_id, job_type, payload, workspace)
        finally:
            key_path.unlink(missing_ok=True)


def main():
    server = os.getenv("PUBLISHER_URL", "https://publisher.smarbiz.sbs")
    max_jobs = int(os.getenv("PUBLISHER_MAX_JOBS", "3"))
    CustomBuildMacAgent(server, max_jobs=max_jobs).run()


if __name__ == "__main__":
    main()
