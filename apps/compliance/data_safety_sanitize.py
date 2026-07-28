from __future__ import annotations

import csv
import io
import re

from .data_safety import DATA_ID_TOKENS, fill_data_safety_template as _fill_data_safety_template


ACCOUNT_CONDITIONAL_QUESTION_PREFIXES = (
    "PSL_HAS_OUTSIDE_APP_ACCOUNTS",
    "PSL_ACCOUNT_DELETION_URL",
    "PSL_ACM_SPECIFY",
)


def strict_data_safety_csv(profile) -> str:
    """Generate and sanitize the exact CSV that may leave Publisher."""
    generated = _fill_data_safety_template(profile)
    return clear_unselected_data_answers(generated, profile) if generated else ""


def clear_unselected_data_answers(csv_text: str, profile) -> str:
    """Make the generated CSV reflect only currently applicable answers.

    Exported Play Console templates may contain selections from an earlier
    declaration. Google rejects those stale values even when they are explicit
    ``FALSE`` values, so this pass is authoritative: inactive data types and
    conditional account/deletion questions are completely blanked.
    """
    if not csv_text.strip():
        return csv_text

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []
    if not fieldnames:
        return csv_text

    question_key = _find_column(fieldnames, "question id")
    response_id_key = _find_column(fieldnames, "response id")
    response_value_key = _find_column(fieldnames, "response value")
    if not question_key or not response_value_key:
        return csv_text

    practices = profile.data_practices or {}
    data_types = practices.get("data_types", {}) or {}
    active_keys = {
        key
        for key, item in data_types.items()
        if isinstance(item, dict) and (bool(item.get("collected")) or bool(item.get("shared")))
    }
    active_tokens = {
        _machine(token)
        for key in active_keys
        for token in DATA_ID_TOKENS.get(key, ())
        if token
    }
    has_active_data = bool(active_keys)
    account_creation = _account_creation(profile)
    deletion_supported = _deletion_supported(profile)

    rows = [dict(row) for row in reader]
    for row in rows:
        question_id = _machine(row.get(question_key, ""))
        response_id = _machine(row.get(response_id_key, "")) if response_id_key else ""

        if question_id.startswith("PSL_DATA_USAGE_RESPONSES_"):
            # Conditional usage rows exist only for data types selected in the
            # parent matrix. FALSE is still an answer and is therefore invalid.
            if not _contains_active_token(question_id, active_tokens):
                row[response_value_key] = ""
                continue

        if question_id.startswith("PSL_DATA_TYPES_") and response_id:
            if not _contains_active_token(response_id, active_tokens):
                row[response_value_key] = ""
                continue

        # The original generator historically used bool(data_types), which is
        # true even when every stored item is inactive. Correct both exported
        # representations of the top-level collection question here.
        if question_id == "PSL_DATA_COLLECTION_COLLECTS_PERSONAL_DATA":
            row[response_value_key] = "TRUE" if has_active_data else "FALSE"
            continue

        if question_id == "PSL_DATA_COLLECTION":
            yes_no = _yes_no_response(response_id)
            if yes_no is not None:
                row[response_value_key] = "TRUE" if yes_no == has_active_data else ""
                continue

        if not account_creation and any(
            question_id.startswith(prefix) for prefix in ACCOUNT_CONDITIONAL_QUESTION_PREFIXES
        ):
            row[response_value_key] = ""
            continue

        if not deletion_supported and question_id.startswith("PSL_DATA_DELETION_URL"):
            row[response_value_key] = ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _account_creation(profile) -> bool:
    practices = profile.data_practices or {}
    if getattr(profile, "account_deletion", "") == "not_applicable":
        return False
    return bool(
        practices.get("account_creation")
        or getattr(profile.app, "requires_login", False)
        or getattr(profile, "app_access", "") == "login"
    )


def _deletion_supported(profile) -> bool:
    account_deletion = getattr(profile, "account_deletion", "")
    if account_deletion in {"in_app", "web", "support"}:
        return True
    if account_deletion in {"unavailable", "not_applicable"}:
        return False
    return bool((profile.data_practices or {}).get("deletion_request", False))


def _contains_active_token(value: str, active_tokens: set[str]) -> bool:
    return any(token in value for token in active_tokens)


def _yes_no_response(response_id: str) -> bool | None:
    if response_id.endswith("_YES") or response_id == "YES":
        return True
    if response_id.endswith("_NO") or response_id == "NO":
        return False
    return None


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
