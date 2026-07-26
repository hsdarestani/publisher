from __future__ import annotations

import base64
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

from django.utils import timezone

from .models import AndroidSigningCredential


_SHA256_RE = re.compile(r"SHA256:\s*([0-9A-F:]+)", re.IGNORECASE)
_DN_UNSAFE_RE = re.compile(r"[^A-Za-z0-9 ._\-]")


def _clean_dn(value: str) -> str:
    """Return a conservative X.500 value accepted by keytool without escaping.

    Characters such as ``+``, ``,`` and ``=`` are structural in a distinguished
    name. Customer names must never be interpolated into ``-dname`` unchanged.
    """

    text = (value or "A Plus Solution GmbH").replace("+", " Plus ")
    text = _DN_UNSAFE_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return (text or "A Plus Solution GmbH")[:100]


def ensure_android_signing(app) -> AndroidSigningCredential:
    existing = AndroidSigningCredential.objects.filter(app=app).first()
    if existing:
        return existing

    alias = "upload"
    password = secrets.token_urlsafe(28)
    organization = _clean_dn(app.client_name or "A Plus Solution GmbH")
    common_name = _clean_dn(app.name)

    with tempfile.TemporaryDirectory(prefix="aplus-android-key-") as tmp:
        key_path = Path(tmp) / "upload-keystore.jks"
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        try:
            subprocess.run(
                [
                    "keytool",
                    "-genkeypair",
                    "-noprompt",
                    "-v",
                    "-keystore",
                    str(key_path),
                    "-storetype",
                    "PKCS12",
                    "-keyalg",
                    "RSA",
                    "-keysize",
                    "4096",
                    "-validity",
                    "10000",
                    "-alias",
                    alias,
                    "-storepass",
                    password,
                    "-keypass",
                    password,
                    "-dname",
                    f"CN={common_name}, OU=Mobile Apps, O={organization}, C=DE",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            details = subprocess.run(
                [
                    "keytool",
                    "-list",
                    "-v",
                    "-keystore",
                    str(key_path),
                    "-storepass",
                    password,
                    "-alias",
                    alias,
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout
        except FileNotFoundError as exc:
            raise RuntimeError("Java keytool is not installed on the Publisher server.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()[-2000:]
            raise RuntimeError(f"Android upload-key generation failed: {detail}") from exc

        match = _SHA256_RE.search(details)
        fingerprint = match.group(1).upper() if match else ""
        payload = {
            "keystore_base64": base64.b64encode(key_path.read_bytes()).decode("ascii"),
            "key_alias": alias,
            "store_password": password,
            "key_password": password,
            "store_type": "PKCS12",
            "created_at": timezone.now().isoformat(),
        }

    credential = AndroidSigningCredential(app=app, certificate_sha256=fingerprint)
    credential.set_credentials(payload)
    credential.save()
    return credential
