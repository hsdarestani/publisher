from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.integrations.google_play import GooglePlayClient
from apps.integrations.google_play_cloud import verify_cloud_token
from apps.publisher.models import MobileApp

from .data_safety import fill_data_safety_template
from .forms import ComplianceOverrideForm, ComplianceProfileForm
from .models import ComplianceProfile, ComplianceRun
from .services import get_or_create_profile, issue_companion_token
from .tasks import execute_compliance_run


@login_required
def compliance_list(request):
    apps = MobileApp.objects.prefetch_related("localizations", "assets").select_related("google_account")
    profiles = {profile.app_id: profile for profile in ComplianceProfile.objects.select_related("app")}
    rows = [{"app": app, "profile": profiles.get(app.pk)} for app in apps if app.supports_android]
    return render(request, "compliance/list.html", {"rows": rows})


@login_required
def compliance_detail(request, app_pk):
    app = get_object_or_404(
        MobileApp.objects.prefetch_related("localizations", "assets", "releases__builds"),
        pk=app_pk,
    )
    profile = get_or_create_profile(app)
    return render(
        request,
        "compliance/detail.html",
        {
            "app": app,
            "profile": profile,
            "runs": profile.runs.all()[:12],
            "official_sections": ["Store listing", "Images", "Data Safety with current CSV template"],
            "companion_sections": ["Privacy policy URL", "App access", "Ads", "Target audience", "Content rating"],
        },
    )


@login_required
def compliance_edit(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    profile = get_or_create_profile(app)
    form = ComplianceProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Compliance inputs saved. Run Generate pack to rebuild every declaration.")
        return redirect(profile)
    return render(
        request,
        "shared/form.html",
        {"form": form, "title": f"Compliance inputs · {app.name}", "back_url": profile.get_absolute_url()},
    )


@login_required
def compliance_overrides(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    profile = get_or_create_profile(app)
    initial = {
        "data_practices_json": json.dumps(profile.data_practices, indent=2, ensure_ascii=False),
        "content_rating_json": json.dumps(profile.content_rating_answers, indent=2, ensure_ascii=False),
    }
    form = ComplianceOverrideForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        profile.data_practices = form.cleaned_data["data_practices_json"]
        profile.content_rating_answers = form.cleaned_data["content_rating_json"]
        profile.save(update_fields=["data_practices", "content_rating_answers", "updated_at"])
        messages.success(request, "Expert overrides saved.")
        return redirect(profile)
    return render(
        request,
        "shared/form.html",
        {"form": form, "title": f"Expert compliance overrides · {app.name}", "back_url": profile.get_absolute_url()},
    )


@login_required
@require_POST
def compliance_action(request, app_pk, action):
    app = get_object_or_404(MobileApp, pk=app_pk)
    profile = get_or_create_profile(app)
    mapping = {"generate": "generate", "analyze": "analyze", "apply": "apply"}
    if action not in mapping:
        raise Http404
    active = profile.runs.filter(action=mapping[action], status__in=["queued", "running"]).first()
    if active:
        messages.info(request, f"{active.get_action_display()} is already running.")
        return redirect("compliance_run", pk=active.pk)
    run = ComplianceRun.objects.create(profile=profile, action=mapping[action])
    execute_compliance_run.delay(run.pk)
    messages.success(request, f"{run.get_action_display()} queued.")
    return redirect("compliance_run", pk=run.pk)


@login_required
def compliance_run(request, pk):
    run = get_object_or_404(ComplianceRun.objects.select_related("profile", "profile__app"), pk=pk)
    return render(request, "compliance/run.html", {"run": run})


@login_required
@require_GET
def download_pack(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    profile = get_or_create_profile(app)
    strict_csv = fill_data_safety_template(profile)
    if strict_csv and strict_csv != profile.data_safety_csv:
        profile.data_safety_csv = strict_csv
        profile.save(update_fields=["data_safety_csv", "updated_at"])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("privacy-policy.txt", profile.privacy_policy_text or "Generate the compliance pack first.")
        archive.writestr("source-analysis.json", json.dumps(profile.source_analysis, indent=2, ensure_ascii=False))
        archive.writestr("data-practices.json", json.dumps(profile.data_practices, indent=2, ensure_ascii=False))
        archive.writestr("content-rating.json", json.dumps(profile.content_rating_answers, indent=2, ensure_ascii=False))
        archive.writestr("play-console-autofill.json", json.dumps(profile.console_autofill, indent=2, ensure_ascii=False))
        if profile.data_safety_csv:
            archive.writestr("data-safety-filled.csv", profile.data_safety_csv)
        archive.writestr(
            "README.txt",
            "A+ Publisher Google Play compliance pack\n\n"
            "API-managed: localized store listing, visual assets, and Data Safety when the current CSV template is present.\n"
            "Console-managed: app access, ads, target audience, content rating, and policy URL. Use A+ Play Console Companion.\n"
            "All legal and policy declarations must be verified by the developer before production submission.\n",
        )
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{app.slug}-google-play-compliance.zip"'
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def create_companion_session(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    profile = get_or_create_profile(app)
    token = issue_companion_token(profile)
    url = request.build_absolute_uri(f"/compliance/companion/{token}/payload.json")
    messages.success(request, "A secure 30-minute Play Console Companion session was created.")
    return render(request, "compliance/companion_session.html", {"profile": profile, "payload_url": url})


@require_GET
def companion_payload(request, token):
    profile = get_object_or_404(ComplianceProfile.objects.select_related("app"), companion_token=token)
    if not profile.companion_token_valid:
        return JsonResponse({"error": "expired"}, status=410)
    response = JsonResponse(profile.console_autofill)
    response["Cache-Control"] = "no-store"
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Credentials"] = "false"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def google_cloud_payload(request, run_id):
    token = request.GET.get("token", "")
    try:
        verify_cloud_token(token, run_id)
    except signing.BadSignature:
        return JsonResponse({"error": "invalid_or_expired_token"}, status=403)

    run = get_object_or_404(
        ComplianceRun.objects.select_related("profile", "profile__app").prefetch_related(
            "profile__app__localizations", "profile__app__assets"
        ),
        pk=run_id,
        action="apply",
    )
    app = run.profile.app
    strict_csv = fill_data_safety_template(run.profile)
    if strict_csv and strict_csv != run.profile.data_safety_csv:
        run.profile.data_safety_csv = strict_csv
        run.profile.save(update_fields=["data_safety_csv", "updated_at"])
    assets = []
    for asset in app.assets.all():
        if asset.platform not in {"android", "shared"}:
            continue
        image_type = GooglePlayClient._image_type(asset)
        if not image_type or not asset.file:
            continue
        assets.append(
            {
                "locale": asset.locale,
                "image_type": image_type,
                "sort_order": asset.sort_order,
                "name": asset.file.name,
                "url": request.build_absolute_uri(asset.file.url),
            }
        )

    payload = {
        "operation": "apply_compliance",
        "package_name": app.package_name,
        "localizations": [
            {
                "locale": loc.locale,
                "title": loc.title,
                "short_description": loc.short_description or loc.subtitle,
                "full_description": loc.full_description,
                "video": "",
            }
            for loc in app.localizations.all()
        ],
        "assets": assets,
        "data_safety_csv": run.profile.data_safety_csv,
    }
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@csrf_exempt
@require_POST
def google_cloud_callback(request, run_id):
    token = request.GET.get("token", "")
    try:
        verify_cloud_token(token, run_id)
    except signing.BadSignature:
        return JsonResponse({"error": "invalid_or_expired_token"}, status=403)

    run = get_object_or_404(ComplianceRun.objects.select_related("profile", "profile__app"), pk=run_id, action="apply")
    if run.status not in {"queued", "running"}:
        return JsonResponse({"ok": True, "status": run.status, "duplicate": True})
    try:
        result = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    profile = run.profile
    if result.get("success"):
        applied = ["Store listing and images"]
        skipped = []
        warnings = list(result.get("warnings", []))
        if result.get("data_safety_applied"):
            applied.append("Data safety")
        elif result.get("data_safety_error"):
            skipped.append("Data safety: Google rejected the generated declaration; the store listing and images were still applied.")
            if result["data_safety_error"] not in " ".join(warnings):
                warnings.append(result["data_safety_error"])
        else:
            skipped.append(
                "Data safety: upload an exported Play Console CSV template once so Publisher can preserve Google's current question IDs."
            )
        for label in ("Privacy policy", "App access", "Ads declaration", "Target audience", "Content rating"):
            skipped.append(f"{label}: no public Google Play API; prepared for A+ Play Console Companion autofill.")
        run.result = {
            "applied": applied,
            "skipped": skipped,
            "warnings": warnings,
            "execution": "github-actions",
            "cloud_result": result,
        }
        run.status = "partial" if skipped else "succeeded"
        run.progress = 100
        run.error = ""
        run.append_log(
            f"Google Play operation completed on GitHub Actions: {result.get('listing_count', 0)} listings, "
            f"{result.get('image_count', 0)} images."
        )
        if result.get("data_safety_error"):
            run.append_log("Store content was committed successfully; Data Safety remains pending and can be retried independently.")
        profile.status = "partially_applied" if skipped else "applied"
        profile.last_applied_at = timezone.now()
        profile.last_error = result.get("data_safety_error", "")
        profile.save(update_fields=["status", "last_applied_at", "last_error", "updated_at"])
    else:
        run.status = "failed"
        run.progress = 100
        run.error = result.get("error", "Google Play cloud operation failed.")
        run.result = {"execution": "github-actions", "cloud_result": result}
        run.append_log(f"Google Play cloud operation failed: {run.error}")
        profile.status = "failed"
        profile.last_error = run.error
        profile.save(update_fields=["status", "last_error", "updated_at"])

    run.finished_at = timezone.now()
    run.save(update_fields=["status", "progress", "error", "result", "logs", "finished_at", "updated_at"])
    return JsonResponse({"ok": True, "status": run.status})


@require_GET
def public_privacy_policy(request, slug):
    app = get_object_or_404(MobileApp, slug=slug)
    profile = get_or_create_profile(app)
    if not profile.privacy_policy_text:
        raise Http404("Privacy policy has not been generated yet.")
    return render(request, "compliance/privacy_policy.html", {"app": app, "profile": profile})


@login_required
@require_GET
def download_companion_extension(request):
    root = Path(__file__).resolve().parent / "companion_extension"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.glob("*"):
            if path.is_file():
                archive.write(path, path.name)
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="a-plus-play-console-companion.zip"'
    response["Cache-Control"] = "no-store"
    return response
