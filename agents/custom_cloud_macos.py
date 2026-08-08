#!/usr/bin/env python3
"""Cloud Mac wrapper that exposes short-lived Apple signing data to custom builds.

App Store Connect API keys, Distribution private keys and provisioning profiles
exist on the runner only for the duration of the claimed job. The distribution
private key is generated/stored encrypted by Publisher and imported into an
ephemeral macOS keychain; the profile is installed only for this build.
"""
from __future__ import annotations

import base64
import os
import secrets
import shlex
import shutil
import subprocess
from pathlib import Path

from cloud_macos import CloudMacAgent


class CustomBuildMacAgent(CloudMacAgent):
    def _fetch_ios_signing(self, job_id):
        response = self.session.post(
            f"{self.server}/apps/agent-api/jobs/{job_id}/ios-signing/",
            timeout=45,
        )
        if response.status_code == 409:
            raise RuntimeError("Publisher iOS Distribution signing/profile is not provisioned yet.")
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _run_local(command, *, input_text=None, label=None):
        """Run a local signing command without ever echoing secret arguments.

        subprocess.CalledProcessError includes the whole argv, which may contain
        temporary keychain/P12 passwords. Convert failures to a sanitized error
        that contains only stdout/stderr from the command.
        """
        try:
            return subprocess.run(
                command,
                input=input_text,
                text=True,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "unknown error").strip()
            if len(detail) > 4000:
                detail = detail[-4000:]
            raise RuntimeError(f"{label or Path(command[0]).name} failed: {detail}") from None

    @staticmethod
    def _openssl3():
        candidates = [
            "/opt/homebrew/opt/openssl@3/bin/openssl",
            "/usr/local/opt/openssl@3/bin/openssl",
            shutil.which("openssl"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        raise RuntimeError("OpenSSL is not available on Cloud Mac.")

    def _install_distribution_signing(self, job_id, workspace):
        signing = self._fetch_ios_signing(job_id)
        workspace = Path(workspace)
        key_pem = workspace / "APlusPublisherDistributionKey.pem"
        cert_der = workspace / "APlusPublisherDistribution.cer"
        cert_pem = workspace / "APlusPublisherDistribution.pem"
        p12_path = workspace / "APlusPublisherDistribution.p12"
        keychain_path = workspace / "APlusPublisherSigning.keychain-db"

        key_pem.write_text(signing["private_key_pem"])
        key_pem.chmod(0o600)
        cert_der.write_bytes(base64.b64decode(signing["certificate_content_base64"]))
        profile_bytes = base64.b64decode(signing["profile_content_base64"])

        profile_uuid = signing["profile_uuid"]
        profiles_dir = Path.home() / "Library" / "MobileDevice" / "Provisioning Profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_path = profiles_dir / f"{profile_uuid}.mobileprovision"
        profile_path.write_bytes(profile_bytes)
        profile_path.chmod(0o600)

        keychain_password = secrets.token_urlsafe(32)
        p12_password = secrets.token_urlsafe(32)
        openssl = self._openssl3()
        self._run_local(
            [openssl, "x509", "-inform", "DER", "-in", str(cert_der), "-out", str(cert_pem)],
            label="Apple certificate conversion",
        )
        self._run_local(
            ["security", "create-keychain", "-p", keychain_password, str(keychain_path)],
            label="Temporary keychain creation",
        )
        self._run_local(
            ["security", "set-keychain-settings", "-lut", "21600", str(keychain_path)],
            label="Temporary keychain settings",
        )
        self._run_local(
            ["security", "unlock-keychain", "-p", keychain_password, str(keychain_path)],
            label="Temporary keychain unlock",
        )

        existing_raw = self._run_local(
            ["security", "list-keychains", "-d", "user"],
            label="Keychain list",
        ).stdout
        existing = []
        for line in existing_raw.splitlines():
            existing.extend(shlex.split(line.strip()))
        keychains = [str(keychain_path)] + [item for item in existing if item != str(keychain_path)]
        self._run_local(
            ["security", "list-keychains", "-d", "user", "-s", *keychains],
            label="Keychain search-list update",
        )

        # macOS Security can import an X.509 certificate and its matching
        # unencrypted PKCS#8/OpenSSL private key directly. Prefer this path so
        # we do not depend on PKCS#12 cipher compatibility between OpenSSL and
        # the macOS Security framework.
        direct_import_error = None
        try:
            self._run_local(
                ["security", "import", str(cert_der), "-k", str(keychain_path), "-t", "cert", "-f", "x509"],
                label="Apple Distribution certificate import",
            )
            self._run_local(
                [
                    "security", "import", str(key_pem), "-k", str(keychain_path),
                    "-t", "priv", "-f", "openssl",
                    "-T", "/usr/bin/codesign", "-T", "/usr/bin/security",
                ],
                label="Apple Distribution private-key import",
            )
        except RuntimeError as exc:
            direct_import_error = str(exc)

        identities = self._run_local(
            ["security", "find-identity", "-v", "-p", "codesigning", str(keychain_path)],
            label="Code-signing identity verification",
        ).stdout

        if "Apple Distribution" not in identities:
            # Fallback: OpenSSL 3's default PKCS#12 uses PBES2/AES, which some
            # macOS Security versions reject. -legacy emits the long-supported
            # 3DES/SHA-1 compatibility envelope while the contained RSA key and
            # Apple certificate themselves remain unchanged.
            self._run_local(
                [
                    openssl, "pkcs12", "-export", "-legacy",
                    "-inkey", str(key_pem), "-in", str(cert_pem),
                    "-out", str(p12_path), "-passout", f"pass:{p12_password}",
                    "-name", "A+ Publisher Apple Distribution",
                ],
                label="Legacy-compatible PKCS12 creation",
            )
            self._run_local(
                [
                    "security", "import", str(p12_path), "-k", str(keychain_path),
                    "-f", "pkcs12", "-P", p12_password,
                    "-T", "/usr/bin/codesign", "-T", "/usr/bin/security",
                ],
                label="Apple Distribution PKCS12 import",
            )
            identities = self._run_local(
                ["security", "find-identity", "-v", "-p", "codesigning", str(keychain_path)],
                label="Code-signing identity verification",
            ).stdout

        if "Apple Distribution" not in identities:
            suffix = f" Direct import detail: {direct_import_error}" if direct_import_error else ""
            raise RuntimeError("Apple Distribution signing identity is not available in the temporary keychain." + suffix)

        self._run_local(
            [
                "security", "set-key-partition-list",
                "-S", "apple-tool:,apple:", "-s", "-k", keychain_password,
                str(keychain_path),
            ],
            label="Apple key partition configuration",
        )

        return {
            "profile_path": profile_path,
            "keychain_path": keychain_path,
            "profile_name": signing["profile_name"],
            "profile_uuid": profile_uuid,
            "bundle_id": signing["bundle_id"],
            "temporary_files": [key_pem, cert_der, cert_pem, p12_path],
        }

    def _cleanup_distribution_signing(self, installed):
        if not installed:
            return
        try:
            subprocess.run(
                ["security", "delete-keychain", str(installed["keychain_path"])],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            installed["profile_path"].unlink(missing_ok=True)
            for path in installed["temporary_files"]:
                path.unlink(missing_ok=True)

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
        installed = None

        try:
            installed = self._install_distribution_signing(job_id, workspace)
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
                    "IOS_SIGNING_STYLE": "Manual",
                    "IOS_CODE_SIGN_IDENTITY": "Apple Distribution",
                    "IOS_PROVISIONING_PROFILE_SPECIFIER": installed["profile_name"],
                    "IOS_PROVISIONING_PROFILE_UUID": installed["profile_uuid"],
                    "IOS_SIGNING_KEYCHAIN": str(installed["keychain_path"]),
                }
            )
            config["env"] = custom_env
            payload["build_config"] = config
            return super().build(job_id, job_type, payload, workspace)
        finally:
            self._cleanup_distribution_signing(installed)
            key_path.unlink(missing_ok=True)


def main():
    server = os.getenv("PUBLISHER_URL", "https://publisher.smarbiz.sbs")
    max_jobs = int(os.getenv("PUBLISHER_MAX_JOBS", "3"))
    CustomBuildMacAgent(server, max_jobs=max_jobs).run()


if __name__ == "__main__":
    main()
