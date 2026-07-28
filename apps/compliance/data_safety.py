from __future__ import annotations

import csv
import io
import re
from collections import defaultdict


DATA_LABELS = {
    "location.precise": "Precise location",
    "location.approximate": "Approximate location",
    "personal_info.name": "Name",
    "personal_info.email": "Email address",
    "personal_info.phone": "Phone number",
    "personal_info.other": "Other personal info",
    "user_ids": "User IDs",
    "financial_info.purchase_history": "Purchase history",
    "photos.files": "Photos and videos",
    "files.documents": "Files and docs",
    "contacts": "Contacts",
    "audio.voice": "Voice or sound recordings",
    "app_activity.app_interactions": "App interactions",
    "app_activity.notifications": "Other user-generated content",
    "diagnostics.crash_logs": "Crash logs",
    "diagnostics.other": "Diagnostics",
    "device.identifiers": "Device or other IDs",
}

DATA_ID_TOKENS = {
    "location.precise": ("PRECISE_LOCATION",),
    "location.approximate": ("APPROX_LOCATION", "APPROXIMATE_LOCATION"),
    "personal_info.name": ("PSL_NAME",),
    "personal_info.email": ("EMAIL_ADDRESS",),
    "personal_info.phone": ("PHONE_NUMBER",),
    "personal_info.other": ("OTHER_PERSONAL_INFO",),
    "user_ids": ("USER_IDS", "USER_ID"),
    "financial_info.purchase_history": ("PURCHASE_HISTORY",),
    "photos.files": ("PHOTOS", "VIDEOS"),
    "files.documents": ("FILES_AND_DOCS", "FILES_AND_DOCUMENTS"),
    "contacts": ("CONTACTS",),
    "audio.voice": ("VOICE_OR_SOUND_RECORDINGS", "AUDIO"),
    "app_activity.app_interactions": ("APP_INTERACTIONS",),
    "app_activity.notifications": ("OTHER_USER_GENERATED_CONTENT",),
    "diagnostics.crash_logs": ("CRASH_LOGS",),
    "diagnostics.other": ("DIAGNOSTICS",),
    "device.identifiers": ("DEVICE_OR_OTHER_IDS", "DEVICE_IDENTIFIERS"),
}

PURPOSE_TOKENS = {
    "app_functionality": ("APP_FUNCTIONALITY",),
    "analytics": ("ANALYTICS",),
    "account_management": ("ACCOUNT_MANAGEMENT",),
    "advertising": ("ADVERTISING", "MARKETING"),
    "fraud_prevention": ("FRAUD_PREVENTION", "SECURITY", "COMPLIANCE"),
    "personalization": ("PERSONALIZATION",),
    "developer_communications": ("DEVELOPER_COMMUNICATIONS",),
}


def fill_data_safety_template(profile) -> str:
    """Fill Google's exported CSV while enforcing its choice constraints."""
    if not profile.data_safety_template:
        return ""
    try:
        profile.data_safety_template.open("rb")
        raw = profile.data_safety_template.read()
        profile.data_safety_template.close()
    except Exception:
        return ""

    reader = csv.DictReader(io.StringIO(_decode_csv(raw)))
    fieldnames = reader.fieldnames or []
    if not fieldnames:
        return ""

    columns = {
        "question_id": _find_column(fieldnames, "question id"),
        "response_id": _find_column(fieldnames, "response id") or _find_column(fieldnames, "response", exclude="value"),
        "response_value": _find_column(fieldnames, "response value"),
        "requirement": _find_column(fieldnames, "answer requirement"),
        "label": _find_column(fieldnames, "human-friendly question label") or _find_column(fieldnames, "question"),
    }
    response_key = columns["response_value"]
    if not response_key:
        return ""

    rows = [dict(row) for row in reader]
    originals = [str(row.get(response_key, "") or "").strip().upper() for row in rows]
    decisions: list[bool | None] = []
    for row in rows:
        decision = _csv_response(profile, row, columns)
        decisions.append(decision)
        if decision is None:
            continue
        requirement = _value(row, columns["requirement"]).upper().replace(" ", "_")
        if requirement in {"SINGLE_CHOICE", "MULTIPLE_CHOICE"}:
            row[response_key] = "TRUE" if decision else ""
        else:
            row[response_key] = "TRUE" if decision else "FALSE"

    _enforce_single_choice(rows, originals, decisions, columns)
    _validate_single_choice(rows, columns)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _enforce_single_choice(rows, originals, decisions, columns):
    response_key = columns["response_value"]
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        requirement = _value(row, columns["requirement"]).upper().replace(" ", "_")
        if requirement == "SINGLE_CHOICE":
            groups[_value(row, columns["question_id"]) or f"row:{index}"].append(index)

    for indexes in groups.values():
        selected = [i for i in indexes if str(rows[i].get(response_key, "")).strip().upper() == "TRUE"]
        if len(selected) == 1:
            chosen = selected[0]
        elif selected:
            chosen = max(selected, key=lambda i: _single_choice_score(rows[i], decisions[i], columns))
        else:
            original_selected = [i for i in indexes if originals[i] == "TRUE"]
            if original_selected:
                chosen = original_selected[0]
            else:
                ranked = sorted(indexes, key=lambda i: _single_choice_score(rows[i], decisions[i], columns), reverse=True)
                chosen = ranked[0] if ranked and _single_choice_score(rows[ranked[0]], decisions[ranked[0]], columns) > 0 else None
        for index in indexes:
            rows[index][response_key] = "TRUE" if index == chosen else ""


def _validate_single_choice(rows, columns):
    response_key = columns["response_value"]
    selected = defaultdict(int)
    for index, row in enumerate(rows):
        requirement = _value(row, columns["requirement"]).upper().replace(" ", "_")
        if requirement != "SINGLE_CHOICE":
            continue
        if str(row.get(response_key, "")).strip().upper() == "TRUE":
            selected[_value(row, columns["question_id"]) or f"row:{index}"] += 1
    invalid = [question for question, count in selected.items() if count > 1]
    if invalid:
        raise ValueError(f"Invalid Google Data Safety SINGLE_CHOICE groups: {', '.join(invalid[:8])}")


def _single_choice_score(row, decision, columns):
    base = 100 if decision is True else -100 if decision is False else 0
    response_id = _machine(_value(row, columns["response_id"]))
    label = _value(row, columns["label"]).lower()
    if any(token in response_id for token in ("REQUIRED", "OPTIONAL", "YES", "NO")):
        base += 10
    if any(token in label for token in ("required", "optional", "yes", "no", "erforderlich", "ja", "nein")):
        base += 2
    return base


def _csv_response(profile, row, columns):
    question_id = _machine(_value(row, columns["question_id"]))
    response_id = _machine(_value(row, columns["response_id"]))
    label = _value(row, columns["label"])
    label_lower = label.lower()
    practices = profile.data_practices or {}
    data_types = practices.get("data_types", {})
    matched_key = _match_data_key(question_id, response_id, label_lower, data_types)
    item = data_types.get(matched_key, {}) if matched_key else {}

    yes_no = _yes_no_choice(response_id, label)
    if _contains(label_lower, "collect or share", "erhebt oder teilt", "erhoben oder weitergegeben") and yes_no is not None:
        answer = bool(data_types)
        return answer if yes_no else not answer
    if _contains(label_lower, "encrypted in transit", "bei der übertragung verschlüsselt") and yes_no is not None:
        answer = bool(practices.get("encrypted_in_transit", True))
        return answer if yes_no else not answer
    if ("delet" in label_lower or "lösch" in label_lower) and yes_no is not None:
        answer = bool(practices.get("deletion_request", False))
        return answer if yes_no else not answer

    if "DATA_TYPES" in question_id and matched_key:
        return bool(item)
    if "COLLECTION_AND_SHARING" in question_id or _contains(label_lower, "collected, shared, or both", "erhoben, weitergegeben oder beides"):
        if "ONLY_COLLECTED" in response_id or response_id.endswith("_COLLECTED") or _last_line(label_lower) in {"collected", "erhoben"}:
            return bool(item.get("collected"))
        if "ONLY_SHARED" in response_id or response_id.endswith("_SHARED") or _last_line(label_lower) in {"shared", "weitergegeben"}:
            return bool(item.get("shared"))
        if "BOTH" in response_id:
            return bool(item.get("collected") and item.get("shared"))
    if "EPHEMERAL" in question_id or _contains(label_lower, "processed ephemerally", "sitzungsspezifisch verarbeitet"):
        return bool(item.get("ephemeral", False))
    if "USER_CONTROL" in question_id or _contains(label_lower, "required for your app", "für deine app erforderlich"):
        if "OPTIONAL" in response_id or "users can choose" in label_lower or "nutzer können entscheiden" in label_lower:
            return not bool(item.get("required", False))
        if "REQUIRED" in response_id or "data collection is required" in label_lower or "datenerhebung ist erforderlich" in label_lower:
            return bool(item.get("required", False))
    if "PURPOSE" in question_id or _contains(label_lower, "why is this user data", "warum werden diese nutzerdaten"):
        for purpose, tokens in PURPOSE_TOKENS.items():
            if any(token in response_id for token in tokens):
                return purpose in item.get("purposes", [])

    if matched_key:
        if "COLLECT" in response_id:
            return bool(item.get("collected"))
        if "SHAR" in response_id:
            return bool(item.get("shared"))
        if "REQUIRED" in response_id:
            return bool(item.get("required"))
        if "OPTIONAL" in response_id:
            return not bool(item.get("required"))
        return bool(item)
    return None


def _match_data_key(question_id, response_id, label_lower, data_types):
    machine = f"{question_id} {response_id}"
    for key in data_types:
        if any(token in machine for token in DATA_ID_TOKENS.get(key, ())):
            return key
    matches = []
    for key, label in DATA_LABELS.items():
        if key in data_types and label.lower() in label_lower:
            matches.append((len(label), key))
    return max(matches)[1] if matches else None


def _yes_no_choice(response_id, label):
    if response_id.endswith("_YES") or response_id == "YES":
        return True
    if response_id.endswith("_NO") or response_id == "NO":
        return False
    last = _last_line(label.lower())
    if last in {"yes", "ja"}:
        return True
    if last in {"no", "nein"}:
        return False
    return None


def _find_column(fieldnames, wanted, exclude=None):
    wanted_tokens = set(_normalize_header(wanted).split())
    best = None
    best_score = -1
    for field in fieldnames or []:
        normalized = _normalize_header(field)
        if exclude and exclude in normalized:
            continue
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


def _value(row, key):
    return str(row.get(key, "") or "") if key else ""


def _last_line(value):
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _contains(text, *phrases):
    return any(phrase in text for phrase in phrases)


def _decode_csv(raw):
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
