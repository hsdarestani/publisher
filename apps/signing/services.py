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


def _clean_dn(value: str) -> str:
    return (value or "A+ Solution GmbH").replace(",", " ").strip()[:100]


def ensure_android_signing(app) -> AndroidSigningCredential:
    existing = AndroidSigningCredential.objects.filter(app=app).first()
    if existing:
        return existing

    alias = "upload"
    password = secrets.token_urlsafe(28)
    organization = _clean_dn(app.client_name or "A+ Solution GmbH")
    common_name = _clean_dn(app.name)

    with tempfile.TemporaryDirectory(prefix="aplus-android-key-") as tmp:
        key_path = Path(tmp) / "upload-keystore.jks"
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        subprocess.run(
            [
                "keytool",
                "-genkeypair",
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
