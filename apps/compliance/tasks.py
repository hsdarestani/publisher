from __future__ import annotations

import traceback

from celery import shared_task
from django.utils import timezone

from apps.integrations.google_play_cloud import dispatch_google_play_cloud, is_google_edge_blocked

from .data_safety import fill_data_safety_template
from .data_safety_sanitize import clear_unselected_data_answers
from .models import ComplianceRun
from .services import apply_google_apis, generate_pack


def _strict_data_safety_csv(profile) -> str:
    generated = fill_data_safety_template(profile)
    return clear_unselected_data_answers(generated, profile) if generated else ""


@shared_task
def execute_compliance_run(run_id: int):
    run = ComplianceRun.objects.select_related("profile", "profile__app").get(pk=run_id)
    run.status = "running"
    run.progress = 5
    run.started_at = timezone.now()
    run.error = ""
    run.save(update_fields=["status", "progress", "started_at", "error", "updated_at"])
    profile = run.profile
    try:
        if run.action in {"analyze", "generate"}:
            profile.status = "analyzing"
            profile.save(update_fields=["status", "updated_at"])
            run.append_log("Reading repository metadata, Android permissions and SDK dependencies.")
            run.progress = 30
            run.save(update_fields=["progress", "updated_at"])
            result = generate_pack(profile)
            strict_csv = _strict_data_safety_csv(profile)
            if strict_csv:
                profile.data_safety_csv = strict_csv
                profile.save(update_fields=["data_safety_csv", "updated_at"])
            run.append_log("Compliance pack generated. Privacy policy, declarations and Data Safety evidence are ready.")
            run.result = {
                "status": profile.status,
                "confidence": float(profile.confidence),
                "ai_used": profile.ai_used,
                "ai_model": profile.ai_model,
                "unresolved_questions": profile.unresolved_questions,
                "generated_sections": sorted(result.keys()),
            }
            run.status = "succeeded"
        elif run.action == "apply":
            strict_csv = _strict_data_safety_csv(profile)
            if strict_csv:
                profile.data_safety_csv = strict_csv
                profile.save(update_fields=["data_safety_csv", "updated_at"])
                run.append_log(
                    "Validated Data Safety CSV: choice constraints are valid and conditional answers for unselected data types are blank."
                )
            run.append_log("Applying localized store listing and image assets through the official Google Play API.")
            run.progress = 35
            run.save(update_fields=["progress", "updated_at"])
            try:
                result = apply_google_apis(profile).as_dict()
            except Exception as direct_error:
                if not is_google_edge_blocked(direct_error):
                    raise
                run.append_log(
                    "Google Edge rejected the Publisher server IP with an HTML 403. "
                    "Dispatching the same official API operation to the trusted GitHub cloud runner."
                )
                dispatch = dispatch_google_play_cloud(run.pk)
                run.progress = 50
                run.result = {
                    "execution": "github-actions",
                    "state": "dispatched",
                    "dispatch": dispatch.as_dict(),
                    "direct_error": str(direct_error)[:2000],
                }
                run.save(update_fields=["progress", "result", "logs", "updated_at"])
                return
            run.result = result
            run.status = "partial" if result.get("skipped") else "succeeded"
            run.append_log("Official API-compatible sections were applied. Console-only declarations are available to the companion autofill.")
        else:
            raise RuntimeError(f"Unsupported compliance action: {run.action}")
        run.progress = 100
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "progress", "finished_at", "result", "logs", "updated_at"])
    except Exception as exc:
        profile.status = "failed"
        profile.last_error = str(exc)
        profile.save(update_fields=["status", "last_error", "updated_at"])
        run.status = "failed"
        run.error = str(exc)
        run.logs = (run.logs + "\n" + traceback.format_exc())[-100000:]
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "logs", "finished_at", "updated_at"])
        raise
