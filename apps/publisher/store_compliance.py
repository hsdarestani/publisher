from __future__ import annotations


APPLE_USES_NON_EXEMPT_ENCRYPTION = {
    # A+ Studio's Capacitor client uses platform HTTPS/TLS only and its iOS build
    # explicitly sets ITSAppUsesNonExemptEncryption=NO. It does not ship custom
    # cryptographic algorithms or a separate crypto library.
    "a-studio": False,
}


APPLE_CONTENT_RIGHTS = {
    # A+ Studio lets business users create and publish their own application
    # content and also uses AI-generated output. Its Terms require users to
    # verify content and third-party rights before production use, so the
    # conservative App Store declaration is that third-party content may be used.
    "a-studio": "USES_THIRD_PARTY_CONTENT",
}


APPLE_AGE_RATING_PROFILES = {
    "a-studio": {
        # In-app controls.
        "parentalControls": False,
        "ageAssurance": False,
        # Capabilities. A+ Studio has no browser, social feed, advertising or
        # user-to-user messaging. User-created application content can be
        # published, so declare UGC conservatively even without social discovery.
        "unrestrictedWebAccess": False,
        "userGeneratedContent": True,
        "socialMedia": False,
        "socialMediaAgeRestricted": False,
        "messagingAndChat": False,
        "advertising": False,
        # Medical / wellness.
        "healthOrWellnessTopics": False,
        "medicalOrTreatmentInformation": "NONE",
        # Mature themes.
        "profanityOrCrudeHumor": "NONE",
        "horrorOrFearThemes": "NONE",
        "matureOrSuggestiveThemes": "NONE",
        "alcoholTobaccoOrDrugUseOrReferences": "NONE",
        # Sexuality / nudity.
        "sexualContentOrNudity": "NONE",
        "sexualContentGraphicAndNudity": "NONE",
        # Violence / weapons.
        "violenceCartoonOrFantasy": "NONE",
        "violenceRealistic": "NONE",
        "violenceRealisticProlongedGraphicOrSadistic": "NONE",
        "gunsOrOtherWeapons": "NONE",
        # Chance-based activities.
        "gamblingSimulated": "NONE",
        "contests": "NONE",
        "gambling": False,
        "lootBox": False,
        # Not a Kids-category app and no manual rating override.
        "kidsAgeBand": None,
        "ageRatingOverride": "NONE",
        "ageRatingOverrideV2": "NONE",
        "koreaAgeRatingOverride": "NONE",
    },
}


def apple_uses_non_exempt_encryption(app):
    """Return the reviewed export-compliance answer, or None if not declared."""

    return APPLE_USES_NON_EXEMPT_ENCRYPTION.get(app.slug)


def apple_content_rights_declaration(app):
    """Return the reviewed App Store Content Rights declaration."""

    return APPLE_CONTENT_RIGHTS.get(app.slug)


def apple_age_rating_profile(app):
    """Return an app-specific age-rating questionnaire answer set.

    Unknown apps intentionally return no answers: Publisher must never invent
    store compliance declarations for an unrelated product.
    """

    profile = APPLE_AGE_RATING_PROFILES.get(app.slug)
    return dict(profile) if profile is not None else None
