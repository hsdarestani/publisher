from __future__ import annotations


APPLE_USES_NON_EXEMPT_ENCRYPTION = {
    # A+ Studio's Capacitor client uses platform HTTPS/TLS only and its iOS build
    # explicitly sets ITSAppUsesNonExemptEncryption=NO. It does not ship custom
    # cryptographic algorithms or a separate crypto library.
    "a-studio": False,
    # A+Bau likewise declares ITSAppUsesNonExemptEncryption=NO in its native iOS
    # release configuration and relies on ordinary platform HTTPS/TLS.
    "a-bau": False,
    # Smarbiz is a Capacitor wrapper around the HTTPS web application and does not
    # ship custom/non-exempt cryptographic algorithms.
    "smarbiz": False,
}


APPLE_CONTENT_RIGHTS = {
    # A+ Studio lets business users create and publish their own application
    # content and also uses AI-generated output. Its Terms require users to
    # verify content and third-party rights before production use, so the
    # conservative App Store declaration is that third-party content may be used.
    "a-studio": "USES_THIRD_PARTY_CONTENT",
    # A+Bau allows authenticated business users to attach photos, documents and
    # other project material. Treat this conservatively as possible third-party
    # content rather than claiming the app can never access such material.
    "a-bau": "USES_THIRD_PARTY_CONTENT",
    # Smarbiz users create, upload, review and publish brand/content assets and AI
    # output, so conservatively declare that third-party content may be present.
    "smarbiz": "USES_THIRD_PARTY_CONTENT",
}


_BASE_BUSINESS_AGE_RATING = {
    # In-app controls.
    "parentalControls": False,
    "ageAssurance": False,
    # Capabilities.
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
    # These business apps are not in the Kids category and do not need manual
    # regional/global rating overrides.
    "kidsAgeBand": None,
    "ageRatingOverrideV2": "NONE",
    "koreaAgeRatingOverride": "NONE",
}


APPLE_AGE_RATING_PROFILES = {
    "a-studio": dict(_BASE_BUSINESS_AGE_RATING),
    # A+Bau is a restricted-access construction/business ERP. Users can create
    # project records, reports, photos and documents, hence UGC is declared
    # conservatively. It has no unrestricted browser, social network, advertising,
    # gambling, weapons/violence or adult-content feature.
    "a-bau": dict(_BASE_BUSINESS_AGE_RATING),
    # Smarbiz is a business content workspace. Users can create/upload their own
    # content, but it has no unrestricted browser, mature-content feature,
    # gambling, weapons, advertising or medical/treatment functionality.
    "smarbiz": dict(_BASE_BUSINESS_AGE_RATING),
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
