from __future__ import annotations

import csv
import io
import re

from .data_safety import DATA_ID_TOKENS
from .data_safety_sanitize import (
    clear_unselected_data_answers as _base_clear_unselected_data_answers,
    strict_data_safety_csv as _base_strict_data_safety_csv,
)


def strict_data_safety_csv(profile) -> str:
    """Return the final Data Safety CSV after all applicability checks."""
    generated = _base_strict_data_safety_csv(profile)
    return enforce_conditional_applicability(generated, profile) if generated else ""


def clear_unselected_data_answers(csv_text: str, profile) -> str:
    """Compatibility wrapper used by compliance tasks before dispatch."""
    sanitized = _base_clear_unselected_data_answers(csv_text, profile)
    return enforce_conditional_applicability(sanitized, profile) if sanitized else ""


def enforce_conditional_applicability(csv_text: str, profile) -> str:
    """Blank answers Google says are invalid when their parent branch is off.

    The Play Console export contains conditional rows whose stale FALSE/TRUE
    values are still treated as answers by the Data Safety API. Publisher must
    therefore blank them rather than merely setting them to FALSE.
    """
    if not csv_text.strip():
        return csv_text

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []
    if not fieldnames:
        return csv_text

    question_key = _find_column(fieldnames, "question id")
    response_value_key = _find_column(fieldnames, "response value")
    if not question_key or not response_value_key:
        return csv_text

    practices = profile.data_practices or {}
    data_types = practices.get("data_types", {}) or {}

    rows = [dict(row) for row in reader]
    for row in rows:
        question_id = _machine(row.get(question_key, ""))

        # Google currently treats this as a conditional question. Having an app
        # account does not by itself prove that outside-app accounts exist. Only
        # answer when Publisher has explicit evidence for that fact.
        if question_id.startswith("PSL_HAS_OUTSIDE_APP_ACCOUNTS"):
            outside_app_accounts = practices.get("outside_app_accounts")
            if outside_app_accounts is None:
                row[response_value_key] = ""
            else:
                row[response_value_key] = "TRUE" if bool(outside_app_accounts) else "FALSE"
            continue

        if not question_id.startswith("PSL_DATA_USAGE_RESPONSES_"):
            continue

        data_key = _matching_data_key(question_id, data_types)
        item = data_types.get(data_key, {}) if data_key else {}

        # Collection and sharing purpose questions are distinct conditional
        # branches in Google's schema. If a type is only collected, every
        # sharing-purpose row must be blank; if it is only shared, collection
        # purpose rows must be blank.
        if "DATA_USAGE_SHARING_PURPOSE" in question_id and not bool(item.get("shared")):
            row[response_value_key] = ""
            continue
        if "DATA_USAGE_COLLECTION_PURPOSE" in question_id and not bool(item.get("collected")):
            row[response_value_key] = ""
            continue

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _matching_data_key(value: str, data_types: dict) -> str | None:
    matches = []
    for key in data_types:
        for token in DATA_ID_TOKENS.get(key, ()):
            machine_token = _machine(token)
            if machine_token and machine_token in value:
                matches.append((len(machine_token), key))
    return max(matches)[1] if matches else None


def _find_column(fieldnames, wanted):
    wanted_tokens = set(_normalize_header(wanted).split())
    best = None
    best_score = -1
    for field in fieldnames or []:
        normalized = _normalize_header(field)
        tokens = set(normalized.split())
        if wanted_tokens.issubset(tokens):
            score = len(wanted_tokens) * 10 - len(tokens - wanted_tokens)
            if score > best_score:
                best, best_score = field, score
    return best


def _normalize_header(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _machine(value):
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")
