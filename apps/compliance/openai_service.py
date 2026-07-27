from __future__ import annotations

import json
import os
from typing import Any

import requests


SCHEMA = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string"},
        "business_model": {"type": "string"},
        "has_ads": {"type": "boolean"},
        "target_age_groups": {"type": "array", "items": {"type": "string"}},
        "app_access": {"type": "string", "enum": ["unrestricted", "login", "restricted"]},
        "app_access_instructions": {"type": "string"},
        "data_practices": {"type": "object", "additionalProperties": True},
        "content_rating_answers": {"type": "object", "additionalProperties": True},
        "store_declarations": {"type": "object", "additionalProperties": True},
        "privacy_policy_text": {"type": "string"},
        "store_listing": {"type": "object", "additionalProperties": True},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "purpose",
        "business_model",
        "has_ads",
        "target_age_groups",
        "app_access",
        "app_access_instructions",
        "data_practices",
        "content_rating_answers",
        "store_declarations",
        "privacy_policy_text",
        "store_listing",
        "unresolved_questions",
        "confidence",
    ],
    "additionalProperties": False,
}


def configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def generate_compliance_pack(context: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Optionally enrich the deterministic pack with structured OpenAI output.

    Failure is deliberately non-fatal: A+ Publisher always retains its rule-engine
    result when no key, credit, compatible model, or network connection is available.
    """

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_COMPLIANCE_MODEL", "gpt-5-mini").strip()
    if not api_key:
        return None, ""

    instructions = (
        "You are the Google Play compliance analyst inside A+ Publisher. "
        "Use only the supplied app metadata and source evidence. Never claim a data practice "
        "without evidence; place uncertainty in unresolved_questions. Generate concise, accurate "
        "German store and privacy content unless the primary locale is not German. The developer "
        "remains responsible for final legal accuracy. Return only the requested schema."
    )
    payload = {
        "model": model,
        "store": False,
        "instructions": instructions,
        "input": json.dumps(context, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "google_play_compliance_pack",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    }
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        text = body.get("output_text") or _find_output_text(body.get("output", []))
        if not text:
            raise RuntimeError("OpenAI response did not contain structured output text.")
        return json.loads(text), model
    except Exception:
        return None, ""


def _find_output_text(items):
    for item in items or []:
        for part in item.get("content", []) if isinstance(item, dict) else []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                return part.get("text", "")
    return ""
