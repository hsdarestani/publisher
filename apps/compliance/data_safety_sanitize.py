from __future__ import annotations

import csv
import io
import re

from .data_safety import DATA_ID_TOKENS


def clear_unselected_data_answers(csv_text: str, profile) -> str:
    """Remove conditional answers for data types that are not selected.

    Google rejects even an explicit FALSE value in a conditional
    ``PSL_DATA_USAGE_RESPONSES:<TYPE>`` row when the corresponding type was not
    selected in the parent Data Types section. Exported templates can contain
    stale values from an earlier declaration, so these rows must be blanked.
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

    selected_keys = set((profile.data_practices or {}).get("data_types", {}))
    selected_tokens = {
        _machine(token)
        for key in selected_keys
        for token in DATA_ID_TOKENS.get(key, ())
        if token
    }

    rows = [dict(row) for row in reader]
    for row in rows:
        question_id = _machine(row.get(question_key, ""))
        response_id = _machine(row.get(response_id_key, "")) if response_id_key else ""

        if question_id.startswith("PSL_DATA_USAGE_RESPONSES_"):
            # Conditional usage rows are valid only for a selected parent data
            # type. Unknown/future Google types are therefore safely cleared.
            if not any(token in question_id for token in selected_tokens):
                row[response_value_key] = ""
                continue

        if question_id.startswith("PSL_DATA_TYPES_") and response_id:
            # Clear stale selections in the parent type matrix too. A response
            # remains selected only when its machine ID maps to current source
            # evidence/data practices.
            if not any(token in response_id for token in selected_tokens):
                row[response_value_key] = ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


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
