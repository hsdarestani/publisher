from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.publisher.models import MobileApp

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
    # A random, short-lived bearer URL is the authorization boundary. The wildcard
    # allows a locally loaded extension whose chrome-extension:// origin is unknown
    # until installation; cookies and credentials are never accepted here.
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Credentials"] = "false"
    response["Referrer-Policy"] = "no-referrer"
    return response


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
