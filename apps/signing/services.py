from __future__ import annotations

import base64
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from dateutil.parser import isoparse
from django.db import transaction
from django.utils import timezone

from apps.integrations.apple_store import AppleStoreClient

from .models import AndroidSigningCredential, IOSDistributionCredential, IOSProvisioningProfile


_SHA256_RE = re.compile(r"SHA256:\s*([0-9A-F:]+)", re.IGNORECASE)
_DN_UNSAFE_RE = re.compile(r"[^A-Za-z0-9 ._\-]")


def _clean_dn(value: str) -> str:
    """Return a conservative X.500 value accepted by keytool/Apple CSRs."""

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
                    "keytool", "-genkeypair", "-noprompt", "-v",
                    "-keystore", str(key_path), "-storetype", "PKCS12",
                    "-keyalg", "RSA", "-keysize", "4096", "-validity", "10000",
                    "-alias", alias, "-storepass", password, "-keypass", password,
                    "-dname", f"CN={common_name}, OU=Mobile Apps, O={organization}, C=DE",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            details = subprocess.run(
                [
                    "keytool", "-list", "-v", "-keystore", str(key_path),
                    "-storepass", password, "-alias", alias,
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


def _apple_distribution_csr(store_account):
    """Generate an RSA keypair and Apple-compatible CSR.

    Only the CSR leaves Publisher. The private key is returned for encrypted
    storage and is never sent to Apple or committed to a repository.
    """

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    common_name = _clean_dn(f"A+ Publisher {store_account.organization or store_account.name}")
    organization = _clean_dn(store_account.organization or "A Plus Solution GmbH")
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
                    x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
                ]
            )
        )
        .sign(private_key, hashes.SHA256())
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return private_pem, csr_pem


def ensure_ios_distribution_signing(store_account) -> IOSDistributionCredential:
    """Create one Publisher-managed Apple Distribution credential per team."""

    existing = IOSDistributionCredential.objects.filter(store_account=store_account).first()
    if existing:
        return existing

    if store_account.provider != "apple" or not store_account.configured:
        raise RuntimeError("A configured Apple Store account is required for iOS signing.")

    private_pem, csr_pem = _apple_distribution_csr(store_account)
    client = AppleStoreClient(store_account)
    body = {
        "data": {
            "type": "certificates",
            "attributes": {
                "certificateType": "DISTRIBUTION",
                "csrContent": csr_pem,
            },
        }
    }
    item = client.request("POST", "/certificates", data=json.dumps(body))["data"]
    attrs = item.get("attributes", {})
    certificate_content = attrs.get("certificateContent", "")
    if not certificate_content:
        raise RuntimeError("Apple created a Distribution certificate but returned no certificateContent.")

    expires_at = isoparse(attrs["expirationDate"]) if attrs.get("expirationDate") else None
    credential = IOSDistributionCredential(
        store_account=store_account,
        apple_certificate_id=item["id"],
        certificate_serial_number=attrs.get("serialNumber", ""),
        expires_at=expires_at,
    )
    credential.set_credentials(
        {
            "private_key_pem": private_pem,
            "certificate_content_base64": certificate_content,
            "certificate_type": attrs.get("certificateType", "DISTRIBUTION"),
            "display_name": attrs.get("displayName", "Apple Distribution"),
            "created_at": timezone.now().isoformat(),
        }
    )
    credential.save()
    return credential


def _find_apple_bundle_id(client: AppleStoreClient, identifier: str):
    data = client.request("GET", f"/bundleIds?filter[identifier]={identifier}&limit=10")
    for item in data.get("data", []):
        if item.get("attributes", {}).get("identifier") == identifier:
            return item
    raise RuntimeError(f"Apple Bundle ID resource not found for {identifier}.")


def ensure_ios_app_store_profile(app) -> IOSProvisioningProfile:
    """Create an IOS_APP_STORE profile using Publisher's managed certificate."""

    existing = IOSProvisioningProfile.objects.filter(app=app).first()
    if existing:
        return existing
    if not app.apple_account_id:
        raise RuntimeError("The app is not linked to an Apple Store account.")

    distribution = ensure_ios_distribution_signing(app.apple_account)
    client = AppleStoreClient(app.apple_account)
    bundle = _find_apple_bundle_id(client, app.bundle_id)
    profile_name = f"A+ Publisher {app.bundle_id} App Store"
    body = {
        "data": {
            "type": "profiles",
            "attributes": {
                "name": profile_name,
                "profileType": "IOS_APP_STORE",
            },
            "relationships": {
                "bundleId": {"data": {"type": "bundleIds", "id": bundle["id"]}},
                "certificates": {
                    "data": [
                        {
                            "type": "certificates",
                            "id": distribution.apple_certificate_id,
                        }
                    ]
                },
            },
        }
    }
    item = client.request("POST", "/profiles", data=json.dumps(body))["data"]
    attrs = item.get("attributes", {})
    profile_content = attrs.get("profileContent", "")
    if not profile_content:
        raise RuntimeError("Apple created an App Store profile but returned no profileContent.")

    expires_at = isoparse(attrs["expirationDate"]) if attrs.get("expirationDate") else None
    profile = IOSProvisioningProfile(
        app=app,
        distribution_credential=distribution,
        apple_profile_id=item["id"],
        profile_name=attrs.get("name") or profile_name,
        profile_uuid=attrs.get("uuid", ""),
        expires_at=expires_at,
    )
    profile.set_credentials(
        {
            "profile_content_base64": profile_content,
            "profile_type": attrs.get("profileType", "IOS_APP_STORE"),
            "created_at": timezone.now().isoformat(),
        }
    )
    profile.save()
    return profile


def ensure_ios_signing(app):
    """Idempotently provision both the team certificate and app profile."""

    with transaction.atomic():
        return ensure_ios_app_store_profile(app)
