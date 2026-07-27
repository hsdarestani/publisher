from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.integrations.github_repo import GitHubRepoClient
from apps.integrations.google_play import GooglePlayClient

from .models import ComplianceProfile
from .openai_service import generate_compliance_pack


PERMISSION_DATA_MAP = {
    "ACCESS_FINE_LOCATION": ("location.precise", "Precise location"),
    "ACCESS_COARSE_LOCATION": ("location.approximate", "Approximate location"),
    "CAMERA": ("photos.camera", "Photos or camera"),
    "READ_MEDIA_IMAGES": ("photos.files", "Photos and videos"),
    "READ_EXTERNAL_STORAGE": ("files.documents", "Files and documents"),
    "READ_CONTACTS": ("contacts", "Contacts"),
    "RECORD_AUDIO": ("audio.voice", "Voice or sound recordings"),
    "READ_PHONE_STATE": ("device.identifiers", "Device or other IDs"),
    "POST_NOTIFICATIONS": ("app_activity.notifications", "App interactions"),
}

PACKAGE_RULES = {
    "geolocator": {"data": ["location.precise", "location.approximate"], "purpose": "app_functionality"},
    "google_maps": {"data": ["location.precise", "location.approximate"], "purpose": "app_functionality"},
    "mapbox": {"data": ["location.precise", "location.approximate"], "purpose": "app_functionality"},
    "firebase_analytics": {"data": ["app_activity.app_interactions", "device.identifiers"], "purpose": "analytics"},
    "firebase_crashlytics": {"data": ["diagnostics.crash_logs", "diagnostics.other"], "purpose": "analytics"},
    "sentry": {"data": ["diagnostics.crash_logs", "diagnostics.other"], "purpose": "analytics"},
    "google_mobile_ads": {"data": ["device.identifiers", "app_activity.app_interactions"], "purpose": "advertising"},
    "admob": {"data": ["device.identifiers", "app_activity.app_interactions"], "purpose": "advertising"},
    "image_picker": {"data": ["photos.files"], "purpose": "app_functionality"},
    "file_picker": {"data": ["files.documents"], "purpose": "app_functionality"},
    "firebase_auth": {"data": ["personal_info.email", "personal_info.name", "user_ids"], "purpose": "account_management"},
}

DATA_LABELS = {
    "location.precise": "Precise location",
    "location.approximate": "Approximate location",
    "personal_info.name": "Name",
    "personal_info.email": "Email address",
    "personal_info.phone": "Phone number",
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

PURPOSE_LABELS = {
    "app_functionality": "App functionality",
    "analytics": "Analytics",
    "account_management": "Account management",
    "advertising": "Advertising or marketing",
    "fraud_prevention": "Fraud prevention, security, and compliance",
    "personalization": "Personalization",
    "developer_communications": "Developer communications",
}

AGE_GROUPS = ["5 and under", "6-8", "9-12", "13-15", "16-17", "18 and over"]


@dataclass
class ApplyResult:
    applied: list[str]
    skipped: list[str]
    warnings: list[str]

    def as_dict(self):
        return {"applied": self.applied, "skipped": self.skipped, "warnings": self.warnings}


def get_or_create_profile(app) -> ComplianceProfile:
    defaults = {
        "primary_locale": app.localizations.values_list("locale", flat=True).first() or "de-DE",
        "purpose": _default_purpose(app),
        "app_access": "login" if app.requires_login else "unrestricted",
        "app_access_instructions": app.review_notes,
        "target_age_groups": ["18 and over"],
    }
    profile, _ = ComplianceProfile.objects.get_or_create(app=app, defaults=defaults)
    return profile


def analyze_source(profile: ComplianceProfile) -> dict[str, Any]:
    app = profile.app
    analysis: dict[str, Any] = {
        "repository": app.repository_url,
        "branch": app.default_branch,
        "commit": app.latest_commit_sha,
        "permissions": [],
        "packages": [],
        "detected_data": {},
        "evidence": [],
        "warnings": [],
        "has_ads_dependency": False,
        "requires_login": app.requires_login,
    }
    if not app.repository_url:
        analysis["warnings"].append("Repository URL is missing; only app metadata was analyzed.")
        return analysis

    client = GitHubRepoClient(app.repository_url, app.get_repository_token())
    evidence = client.evidence_files(app.default_branch)
    combined = "\n".join(evidence.values())

    manifest = evidence.get("android/app/src/main/AndroidManifest.xml", "")
    permissions = sorted(set(re.findall(r"android\.permission\.([A-Z0-9_]+)", manifest)))
    analysis["permissions"] = permissions
    for permission in permissions:
        mapped = PERMISSION_DATA_MAP.get(permission)
        if mapped:
            _record_data(analysis, mapped[0], mapped[1], "app_functionality", f"Android permission {permission}")

    dependency_text = "\n".join(
        evidence.get(path, "")
        for path in ("pubspec.yaml", "package.json", "android/app/build.gradle", "android/app/build.gradle.kts")
    ).lower()
    for package, rule in PACKAGE_RULES.items():
        if package not in dependency_text:
            continue
        analysis["packages"].append(package)
        if rule["purpose"] == "advertising":
            analysis["has_ads_dependency"] = True
        for data_type in rule["data"]:
            _record_data(
                analysis,
                data_type,
                DATA_LABELS.get(data_type, data_type),
                rule["purpose"],
                f"Dependency {package}",
            )

    lower = combined.lower()
    if any(token in lower for token in ("login", "sign in", "register", "account", "authentication")):
        analysis["requires_login"] = True
        _record_data(analysis, "personal_info.email", "Email address", "account_management", "Authentication/account source text")
        _record_data(analysis, "user_ids", "User IDs", "account_management", "Authentication/account source text")
    if any(token in lower for token in ("booking", "reservation", "purchase", "payment", "invoice")):
        _record_data(analysis, "financial_info.purchase_history", "Purchase history", "app_functionality", "Booking or transaction source text")
    if any(token in lower for token in ("vehicle", "license plate", "kennzeichen")):
        _record_data(analysis, "personal_info.other", "Other personal info", "app_functionality", "Vehicle information source text")
    if "delete account" in lower or "account deletion" in lower or "konto löschen" in lower:
        analysis["supports_deletion_request"] = True
    else:
        analysis["supports_deletion_request"] = False
        if analysis["requires_login"]:
            analysis["warnings"].append("Account deletion flow was not detected in source evidence.")

    analysis["evidence_files"] = sorted(evidence)
    analysis["packages"] = sorted(set(analysis["packages"]))
    return analysis


def generate_pack(profile: ComplianceProfile) -> dict[str, Any]:
    app = profile.app
    analysis = analyze_source(profile)
    rule_pack = _rule_pack(profile, analysis)
    context = {
        "app": {
            "name": app.name,
            "client_name": app.client_name,
            "package_name": app.package_name,
            "category": app.category,
            "requires_login": app.requires_login,
            "review_notes": app.review_notes,
            "privacy_policy_url": app.privacy_policy_url,
            "support_url": app.support_url,
            "localizations": list(app.localizations.values("locale", "title", "short_description", "full_description")),
        },
        "profile": {
            "primary_locale": profile.primary_locale,
            "purpose": profile.purpose,
            "business_model": profile.business_model,
            "has_ads": profile.has_ads,
            "target_age_groups": profile.target_age_groups,
        },
        "source_analysis": analysis,
        "rule_engine_pack": rule_pack,
    }
    ai_pack, ai_model = generate_compliance_pack(context)
    pack = _merge_ai_pack(rule_pack, ai_pack) if ai_pack else rule_pack

    profile.source_analysis = analysis
    profile.purpose = pack.get("purpose") or profile.purpose or _default_purpose(app)
    profile.business_model = pack.get("business_model", profile.business_model)
    profile.has_ads = bool(pack.get("has_ads", analysis.get("has_ads_dependency", False)))
    profile.target_age_groups = pack.get("target_age_groups") or profile.target_age_groups or ["18 and over"]
    profile.app_access = pack.get("app_access") or ("login" if analysis.get("requires_login") else "unrestricted")
    profile.app_access_instructions = pack.get("app_access_instructions") or app.review_notes
    profile.data_practices = pack.get("data_practices", {})
    profile.content_rating_answers = pack.get("content_rating_answers", {})
    profile.store_declarations = pack.get("store_declarations", {})
    profile.generated_content = {"store_listing": pack.get("store_listing", {})}
    profile.privacy_policy_text = pack.get("privacy_policy_text") or _privacy_policy(profile, analysis)
    profile.unresolved_questions = pack.get("unresolved_questions", [])
    profile.console_autofill = _console_autofill(profile)
    profile.confidence = max(0, min(1, float(pack.get("confidence", 0.78))))
    profile.ai_used = bool(ai_pack)
    profile.ai_model = ai_model
    profile.data_safety_csv = fill_data_safety_template(profile)
    profile.status = "needs_review" if profile.unresolved_questions else "ready"
    profile.last_generated_at = timezone.now()
    profile.last_error = ""
    profile.save()

    if not app.privacy_policy_url:
        app.privacy_policy_url = settings.PUBLIC_URL.rstrip("/") + profile.privacy_policy_url
        app.save(update_fields=["privacy_policy_url", "updated_at"])
    return pack


def apply_google_apis(profile: ComplianceProfile) -> ApplyResult:
    app = profile.app
    applied: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    if not app.google_account or not app.google_account.configured:
        raise RuntimeError("Google Play account is not configured for this app.")
    client = GooglePlayClient(app.google_account)

    metadata_result = client.apply_store_content(app, app.localizations.all(), app.assets.all())
    applied.append("Store listing and images")
    if metadata_result.get("warnings"):
        warnings.extend(metadata_result["warnings"])

    if profile.data_safety_csv.strip():
        client.apply_data_safety(app.package_name, profile.data_safety_csv)
        applied.append("Data safety")
    else:
        skipped.append("Data safety: upload an exported Play Console CSV template once so Publisher can preserve Google's current question IDs.")

    for label in ("Privacy policy", "App access", "Ads declaration", "Target audience", "Content rating"):
        skipped.append(f"{label}: no public Google Play API; prepared for A+ Play Console Companion autofill.")

    profile.status = "applied" if not skipped else "partially_applied"
    profile.last_applied_at = timezone.now()
    profile.last_error = ""
    profile.save(update_fields=["status", "last_applied_at", "last_error", "updated_at"])
    return ApplyResult(applied, skipped, warnings)


def fill_data_safety_template(profile: ComplianceProfile) -> str:
    if not profile.data_safety_template:
        return ""
    try:
        profile.data_safety_template.open("rb")
        raw = profile.data_safety_template.read()
        profile.data_safety_template.close()
    except Exception:
        return ""
    text = _decode_csv(raw)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in reader:
        row = dict(row)
        response_key = _find_column(reader.fieldnames, "response value")
        if response_key:
            decision = _csv_response(profile, row)
            if decision is not None:
                row[response_key] = "TRUE" if decision else "FALSE"
        writer.writerow(row)
    return output.getvalue()


def issue_companion_token(profile: ComplianceProfile) -> str:
    profile.companion_token_expires_at = timezone.now() + timedelta(minutes=30)
    profile.console_autofill = _console_autofill(profile)
    profile.save(update_fields=["companion_token_expires_at", "console_autofill", "updated_at"])
    return str(profile.companion_token)


def _rule_pack(profile: ComplianceProfile, analysis: dict[str, Any]) -> dict[str, Any]:
    app = profile.app
    data_types = {}
    for key, item in analysis.get("detected_data", {}).items():
        data_types[key] = {
            "label": item.get("label", DATA_LABELS.get(key, key)),
            "collected": True,
            "shared": False,
            "required": key in {"personal_info.email", "user_ids"} and analysis.get("requires_login", False),
            "purposes": sorted(item.get("purposes") or ["app_functionality"]),
            "evidence": item.get("evidence", []),
        }
    locale = app.localizations.filter(locale=profile.primary_locale).first() or app.localizations.first()
    purpose = profile.purpose or (locale.full_description if locale else "") or _default_purpose(app)
    has_ads = profile.has_ads or analysis.get("has_ads_dependency", False)
    ages = profile.target_age_groups or ["18 and over"]
    access = "login" if analysis.get("requires_login") or app.requires_login else "unrestricted"
    deletion = bool(analysis.get("supports_deletion_request")) or not access == "login"
    privacy_context = {
        "data_types": data_types,
        "encrypted_in_transit": True,
        "deletion_request": deletion,
        "account_creation": access == "login",
    }
    unresolved = list(analysis.get("warnings", []))
    if "financial_info.purchase_history" in data_types:
        unresolved.append("Confirm whether payment data itself is handled by the app or only by an external payment provider.")
    return {
        "purpose": purpose,
        "business_model": profile.business_model or ("service marketplace" if "booking" in purpose.lower() else "digital service"),
        "has_ads": has_ads,
        "target_age_groups": ages,
        "app_access": access,
        "app_access_instructions": app.review_notes or _default_access_instructions(app, access),
        "data_practices": privacy_context,
        "content_rating_answers": {
            "violence": False,
            "sexual_content": False,
            "language": False,
            "controlled_substances": False,
            "gambling": False,
            "user_generated_content": _contains_any(analysis, ["chat", "comment", "upload", "listing"]),
            "location_sharing": "location.precise" in data_types or "location.approximate" in data_types,
        },
        "store_declarations": {
            "contains_ads": has_ads,
            "target_age_groups": ages,
            "designed_for_children": any(age != "18 and over" for age in ages),
            "app_access": access,
            "privacy_policy_url": app.privacy_policy_url or settings.PUBLIC_URL.rstrip("/") + profile.privacy_policy_url,
        },
        "privacy_policy_text": _privacy_policy_from_values(app, purpose, privacy_context, profile.support_email),
        "store_listing": _store_listing(app, locale, purpose),
        "unresolved_questions": sorted(set(unresolved)),
        "confidence": 0.86 if analysis.get("evidence_files") else 0.65,
    }


def _merge_ai_pack(rule_pack: dict, ai_pack: dict | None) -> dict:
    if not ai_pack:
        return rule_pack
    merged = dict(rule_pack)
    for key, value in ai_pack.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    # Deterministic evidence always wins for explicit ad SDKs and detected data.
    if rule_pack.get("has_ads"):
        merged["has_ads"] = True
    deterministic_types = rule_pack.get("data_practices", {}).get("data_types", {})
    ai_data = merged.setdefault("data_practices", {}).setdefault("data_types", {})
    for key, value in deterministic_types.items():
        ai_data.setdefault(key, value)
    merged["unresolved_questions"] = sorted(set(rule_pack.get("unresolved_questions", []) + merged.get("unresolved_questions", [])))
    return merged


def _console_autofill(profile: ComplianceProfile) -> dict[str, Any]:
    app = profile.app
    return {
        "version": 1,
        "app": {"name": app.name, "package_name": app.package_name},
        "privacy_policy": {"url": app.privacy_policy_url or settings.PUBLIC_URL.rstrip("/") + profile.privacy_policy_url},
        "app_access": {
            "mode": profile.app_access,
            "instructions": profile.app_access_instructions or app.review_notes,
            "username": app.review_username,
            "password": app.get_review_password(),
        },
        "ads": {"contains_ads": profile.has_ads},
        "target_audience": {"age_groups": profile.target_age_groups},
        "content_rating": profile.content_rating_answers,
        "data_safety": profile.data_practices,
        "store_listing": profile.generated_content.get("store_listing", {}),
    }


def _record_data(analysis, key, label, purpose, evidence):
    item = analysis["detected_data"].setdefault(key, {"label": label, "purposes": [], "evidence": []})
    if purpose not in item["purposes"]:
        item["purposes"].append(purpose)
    if evidence not in item["evidence"]:
        item["evidence"].append(evidence)


def _default_purpose(app):
    loc = app.localizations.first()
    return (loc.full_description if loc else "") or f"{app.name} provides its advertised mobile application functionality."


def _default_access_instructions(app, access):
    if access == "unrestricted":
        return "All app functionality can be reviewed without credentials."
    return app.review_notes or "Use the reviewer credentials supplied with the app submission to access all restricted functionality."


def _privacy_policy(profile, analysis):
    return _privacy_policy_from_values(profile.app, profile.purpose or _default_purpose(profile.app), profile.data_practices, profile.support_email)


def _privacy_policy_from_values(app, purpose, practices, support_email=""):
    data_types = practices.get("data_types", {})
    locale = "de" if (getattr(app, "compliance", None) and app.compliance.primary_locale.lower().startswith("de")) else "en"
    collected = [item.get("label", DATA_LABELS.get(key, key)) for key, item in data_types.items() if item.get("collected")]
    purposes = sorted({PURPOSE_LABELS.get(p, p.replace("_", " ").title()) for item in data_types.values() for p in item.get("purposes", [])})
    contact = support_email or "support@aplus-solution.de"
    if locale == "de":
        data_text = ", ".join(collected) if collected else "keine personenbezogenen Daten außerhalb technisch notwendiger Verbindungsdaten"
        purpose_text = ", ".join(purposes) if purposes else "Bereitstellung der App-Funktionen"
        return f"""Datenschutzerklärung für {app.name}

Stand: {timezone.localdate().strftime('%d.%m.%Y')}

1. Verantwortlicher
{app.client_name or 'A+ Solution GmbH'} ist für die Verarbeitung personenbezogener Daten in dieser App verantwortlich. Kontakt: {contact}

2. Zweck der App
{purpose}

3. Verarbeitete Daten
Auf Grundlage der aktuellen App-Funktionen können folgende Daten verarbeitet werden: {data_text}. Die tatsächliche Verarbeitung hängt davon ab, welche Funktionen Nutzer aktiv verwenden.

4. Verarbeitungszwecke
Die Daten werden für folgende Zwecke verwendet: {purpose_text}.

5. Weitergabe
Daten werden nicht verkauft. Eine Weitergabe erfolgt nur an technisch erforderliche Dienstleister oder wenn dies gesetzlich vorgeschrieben ist. Eingesetzte SDKs und Hosting-Dienste werden in der Google-Play-Datensicherheitsdeklaration berücksichtigt.

6. Sicherheit und Speicherdauer
Daten werden bei der Übertragung verschlüsselt. Sie werden nur so lange gespeichert, wie es für die jeweiligen Zwecke, vertragliche Pflichten oder gesetzliche Aufbewahrungsfristen erforderlich ist.

7. Rechte der Nutzer
Nutzer können Auskunft, Berichtigung, Löschung, Einschränkung oder Widerspruch verlangen. Anfragen sind an {contact} zu richten.

8. Änderungen
Diese Datenschutzerklärung kann bei Änderungen der App, der eingesetzten Dienste oder der Rechtslage aktualisiert werden.
"""
    data_text = ", ".join(collected) if collected else "no personal data beyond technically necessary connection data"
    purpose_text = ", ".join(purposes) if purposes else "providing the app functionality"
    return f"""Privacy Policy for {app.name}

Effective date: {timezone.localdate().isoformat()}

{app.client_name or 'A+ Solution GmbH'} is responsible for data processing in this app. Contact: {contact}

Purpose: {purpose}

Based on the current app functionality, the app may process: {data_text}. Data is used for {purpose_text}. Data is not sold and is shared only with technically necessary service providers or where legally required. Data is encrypted in transit and retained only as long as required for the stated purposes or legal obligations. Users may request access, correction, deletion, restriction, or objection by contacting {contact}.
"""


def _store_listing(app, locale, purpose):
    if locale:
        return {
            "locale": locale.locale,
            "title": locale.title,
            "short_description": locale.short_description or locale.subtitle,
            "full_description": locale.full_description or purpose,
        }
    return {"locale": "de-DE", "title": app.name[:50], "short_description": purpose[:80], "full_description": purpose}


def _contains_any(analysis, tokens):
    text = json.dumps(analysis, ensure_ascii=False).lower()
    return any(token in text for token in tokens)


def _decode_csv(raw):
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _find_column(fieldnames, wanted):
    wanted = wanted.lower().replace("_", " ")
    for field in fieldnames or []:
        if field.lower().replace("_", " ").strip() == wanted:
            return field
    return None


def _row_text(row):
    return " ".join(str(v or "") for v in row.values()).lower()


def _csv_response(profile: ComplianceProfile, row):
    text = _row_text(row)
    choice = next((str(v or "").lower() for k, v in row.items() if "answer" in k.lower() or "choice" in k.lower()), "")
    practices = profile.data_practices
    data_types = practices.get("data_types", {})

    if "collect or share" in text and ("yes" in choice or "no" in choice):
        answer = bool(data_types)
        return answer if "yes" in choice else not answer
    if "encrypted in transit" in text and ("yes" in choice or "no" in choice):
        answer = bool(practices.get("encrypted_in_transit", True))
        return answer if "yes" in choice else not answer
    if "request" in text and "delet" in text and ("yes" in choice or "no" in choice):
        answer = bool(practices.get("deletion_request", False))
        return answer if "yes" in choice else not answer

    matched_key = None
    for key, label in DATA_LABELS.items():
        if label.lower() in text:
            matched_key = key
            break
    if not matched_key:
        return None
    item = data_types.get(matched_key, {})
    if "collected" in text or "collect" in text:
        return bool(item.get("collected"))
    if "shared" in text or "share" in text:
        return bool(item.get("shared"))
    if "required" in text:
        return bool(item.get("required"))
    for purpose, label in PURPOSE_LABELS.items():
        if label.lower() in text:
            return purpose in item.get("purposes", [])
    return bool(item)
