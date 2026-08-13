from __future__ import annotations


APPLE_REVIEW_CONTACTS = {
    "a-studio": {
        "contactFirstName": "Ashkan",
        "contactLastName": "Asadian",
        "contactPhone": "+491727779721",
        "contactEmail": "info@aplus-solution.de",
    },
    "a-bau": {
        "contactFirstName": "Ashkan",
        "contactLastName": "Asadian",
        "contactPhone": "+491727779721",
        "contactEmail": "info@aplus-solution.de",
    },
}


def apple_review_contact(app) -> dict:
    """Return Publisher-managed App Review contact details for an app.

    App Store Connect requires a real contact first/last name, phone and email
    before a version can be submitted. Keep these operational review details
    separate from customer-facing store metadata.
    """

    return dict(APPLE_REVIEW_CONTACTS.get(app.slug, {}))
