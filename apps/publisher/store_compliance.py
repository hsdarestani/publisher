from __future__ import annotations


APPLE_USES_NON_EXEMPT_ENCRYPTION = {
    # A+ Studio's Capacitor client uses platform HTTPS/TLS only and its iOS build
    # explicitly sets ITSAppUsesNonExemptEncryption=NO. It does not ship custom
    # cryptographic algorithms or a separate crypto library.
    "a-studio": False,
}


def apple_uses_non_exempt_encryption(app):
    """Return the reviewed export-compliance answer, or None if not declared."""

    return APPLE_USES_NON_EXEMPT_ENCRYPTION.get(app.slug)
