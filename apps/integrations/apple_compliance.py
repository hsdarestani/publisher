from __future__ import annotations

import json

from .base import IntegrationError


_EDITABLE_APP_INFO_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "READY_FOR_REVIEW",
    "DEVELOPER_REJECTED",
    "METADATA_REJECTED",
    "REJECTED",
}


def set_content_rights(client, app_id: str, declaration: str):
    """Set the app-level App Store content-rights declaration."""

    if declaration not in {
        "DOES_NOT_USE_THIRD_PARTY_CONTENT",
        "USES_THIRD_PARTY_CONTENT",
    }:
        raise ValueError(f"Unsupported content rights declaration: {declaration}")
    body = {
        "data": {
            "type": "apps",
            "id": str(app_id),
            "attributes": {"contentRightsDeclaration": declaration},
        }
    }
    return client.request(
        "PATCH",
        f"/apps/{app_id}",
        data=json.dumps(body),
    )["data"]


def find_editable_app_info(client, app_id: str):
    """Find the app-info record that applies to the version being prepared."""

    data = client.request(
        "GET",
        f"/apps/{app_id}/appInfos?limit=50",
    ).get("data", [])
    for item in data:
        attrs = item.get("attributes", {})
        state = attrs.get("appStoreState") or attrs.get("state")
        if state in _EDITABLE_APP_INFO_STATES:
            return item
    if len(data) == 1:
        return data[0]
    raise IntegrationError(
        f"No editable App Store appInfo found for app {app_id}."
    )


def read_age_rating_declaration(client, app_info_id: str):
    return client.request(
        "GET",
        f"/appInfos/{app_info_id}/ageRatingDeclaration",
    )["data"]


def set_age_rating_declaration(client, declaration_id: str, attributes: dict):
    """Answer Apple's age-rating questionnaire for one app-level declaration."""

    if not attributes:
        raise ValueError("Age-rating attributes are required.")
    body = {
        "data": {
            "type": "ageRatingDeclarations",
            "id": str(declaration_id),
            "attributes": dict(attributes),
        }
    }
    return client.request(
        "PATCH",
        f"/ageRatingDeclarations/{declaration_id}",
        data=json.dumps(body),
    )["data"]


def apply_app_store_compliance(client, app_id: str, *, content_rights=None, age_rating=None):
    """Apply app-level declarations needed before a review submission."""

    result = {}
    if content_rights is not None:
        app_result = set_content_rights(client, app_id, content_rights)
        result["content_rights"] = app_result.get("attributes", {}).get(
            "contentRightsDeclaration",
            content_rights,
        )

    if age_rating is not None:
        app_info = find_editable_app_info(client, app_id)
        declaration = read_age_rating_declaration(client, app_info["id"])
        updated = set_age_rating_declaration(
            client,
            declaration["id"],
            age_rating,
        )
        result["age_rating_declaration_id"] = updated["id"]
        result["age_rating"] = updated.get("attributes", {})

    return result
