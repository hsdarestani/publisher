#!/usr/bin/env python3
"""Cloud Linux agent wrapper that exposes ephemeral Android signing to custom builds.

Publisher already creates and stores each app's Android upload key. The standard
CloudLinuxAgent injects that key for its own build flow; this wrapper additionally
passes safe, job-scoped environment variables to a custom ``android_command`` so
Capacitor and other non-Flutter projects can sign their AAB without persisting
credentials in the source repository or application build_config.

For release-recovery workflows we can also preserve a successfully signed Android
artifact *before* the Publisher completion callback. This matters when the build
itself succeeds but the reverse artifact upload endpoint is temporarily unhealthy.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil

from cloud_linux import CloudLinuxAgent


class CustomBuildLinuxAgent(CloudLinuxAgent):
    def build(self, job_id, job_type, payload, workspace):
        if job_type == "build_android" and (payload.get("build_config") or {}).get("android_command"):
            signing = payload.get("android_signing") or {}
            missing = [
                key
                for key in ("keystore_base64", "key_alias", "store_password", "key_password")
                if not signing.get(key)
            ]
            if missing:
                raise RuntimeError("Android custom-build signing is incomplete: " + ", ".join(missing))

            payload = dict(payload)
            config = dict(payload.get("build_config") or {})
            custom_env = dict(config.get("env") or {})
            repo_dir = Path(workspace) / "repo"
            custom_env.update(
                {
                    "ANDROID_KEYSTORE_PATH": str(repo_dir / "android" / "upload-keystore.jks"),
                    "ANDROID_KEY_PROPERTIES_PATH": str(repo_dir / "android" / "key.properties"),
                    "ANDROID_KEYSTORE_PASSWORD": signing["store_password"],
                    "ANDROID_KEY_ALIAS": signing["key_alias"],
                    "ANDROID_KEY_PASSWORD": signing["key_password"],
                }
            )
            config["env"] = custom_env
            payload["build_config"] = config

        artifact, metadata = super().build(job_id, job_type, payload, workspace)

        preserve_dir = os.getenv("PUBLISHER_PRESERVE_ARTIFACT_DIR", "").strip()
        if job_type == "build_android" and preserve_dir and artifact:
            target_dir = Path(preserve_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"job-{job_id}-{artifact.name}"
            shutil.copy2(artifact, target)
            print(f"Preserved signed Android artifact before callback: {target}", flush=True)

        return artifact, metadata


def main():
    server = os.getenv("PUBLISHER_URL", "https://publisher.smarbiz.sbs")
    max_jobs = int(os.getenv("PUBLISHER_MAX_JOBS", "3"))
    CustomBuildLinuxAgent(server, max_jobs=max_jobs).run()


if __name__ == "__main__":
    main()
