from __future__ import annotations

from copy import deepcopy

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ComplianceProfile


ACCOUNT_DELETION_QUESTION = "Account deletion flow was not detected in source evidence."
PAYMENT_QUESTION = "Confirm whether payment data itself is handled by the app or only by an external payment provider."
ACCOUNT_DELETION_REQUIRED = (
    "Google Play requires a usable account-deletion method when users can create accounts; "
    "add an in-app, public web, or support deletion path before production."
)
DIRECT_PAYMENT_DETAILS_REQUIRED = (
    "Direct payment handling was selected; describe which payment data reaches the app or backend before production."
)


def _without(items, value):
    return [item for item in items if item != value]


@receiver(post_save, sender=ComplianceProfile)
def apply_review_confirmations(sender, instance: ComplianceProfile, **kwargs):
    """Turn explicit owner confirmations into stable compliance declarations.

    Source analysis should remain conservative. These fields are the human-reviewed
    business facts that source code alone cannot prove. QuerySet.update avoids a
    recursive signal while making the resolved state immediately visible after both
    saving Inputs and regenerating a pack.
    """

    questions = list(instance.unresolved_questions or [])
    practices = deepcopy(instance.data_practices or {})
    declarations = deepcopy(instance.store_declarations or {})
    autofill = deepcopy(instance.console_autofill or {})

    deletion = instance.account_deletion
    if deletion != "unknown":
        questions = _without(questions, ACCOUNT_DELETION_QUESTION)

    deletion_available = deletion in {"in_app", "web", "support"}
    if deletion_available:
        questions = _without(questions, ACCOUNT_DELETION_REQUIRED)
        practices["deletion_request"] = True
        practices["account_deletion_method"] = deletion
        if instance.account_deletion_url:
            practices["account_deletion_url"] = instance.account_deletion_url
        declarations["account_deletion"] = {
            "method": deletion,
            "url": instance.account_deletion_url,
        }
    elif deletion == "not_applicable":
        if instance.app.requires_login or instance.app_access == "login":
            if ACCOUNT_DELETION_REQUIRED not in questions:
                questions.append(ACCOUNT_DELETION_REQUIRED)
        else:
            questions = _without(questions, ACCOUNT_DELETION_REQUIRED)
            practices["deletion_request"] = False
            practices["account_creation"] = False
    elif deletion == "unavailable":
        practices["deletion_request"] = False
        if instance.app.requires_login or instance.app_access == "login":
            if ACCOUNT_DELETION_REQUIRED not in questions:
                questions.append(ACCOUNT_DELETION_REQUIRED)

    payment = instance.payment_handling
    if payment != "unknown":
        questions = _without(questions, PAYMENT_QUESTION)

    payment_info = {
        "handling": payment,
        "details": instance.payment_details.strip(),
    }
    if payment == "none":
        payment_info["payment_data_collected"] = False
        payment_info["external_processor"] = False
        questions = _without(questions, DIRECT_PAYMENT_DETAILS_REQUIRED)
    elif payment == "external":
        payment_info["payment_data_collected"] = False
        payment_info["external_processor"] = True
        questions = _without(questions, DIRECT_PAYMENT_DETAILS_REQUIRED)
    elif payment == "direct":
        payment_info["payment_data_collected"] = True
        payment_info["external_processor"] = False
        if instance.payment_details.strip():
            questions = _without(questions, DIRECT_PAYMENT_DETAILS_REQUIRED)
        elif DIRECT_PAYMENT_DETAILS_REQUIRED not in questions:
            questions.append(DIRECT_PAYMENT_DETAILS_REQUIRED)
    declarations["payment"] = payment_info
    practices["payment_handling"] = payment_info

    autofill.setdefault("data_safety", {}).update(practices)
    autofill["business_confirmations"] = {
        "account_deletion": declarations.get("account_deletion", {"method": deletion}),
        "payment": payment_info,
    }

    questions = sorted(set(questions))
    status = instance.status
    if instance.last_generated_at and status not in {"partially_applied", "applied", "failed", "analyzing"}:
        status = "needs_review" if questions else "ready"

    updates = {
        "unresolved_questions": questions,
        "data_practices": practices,
        "store_declarations": declarations,
        "console_autofill": autofill,
        "status": status,
    }
    changed = any(getattr(instance, key) != value for key, value in updates.items())
    if changed:
        ComplianceProfile.objects.filter(pk=instance.pk).update(**updates)
