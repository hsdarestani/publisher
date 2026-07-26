from __future__ import annotations
import hashlib
import json
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from apps.core.audit import log_event
from .forms import MobileAppForm, LocalizationForm, AssetForm, ReleaseForm, BuildAgentForm
from .models import MobileApp, AppLocalization, AppAsset, Release, Build, BuildAgent, Job, Submission
from .readiness import evaluate_release
from .tasks import enqueue_job, run_job

@login_required
def app_list(request):
    return render(request, "publisher/app_list.html", {"apps": MobileApp.objects.prefetch_related("releases", "metrics").all()})

@login_required
def app_create(request):
    form = MobileAppForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        app = form.save(); log_event(request, "app.create", f"Created {app.name}", app)
        messages.success(request, "Application created.")
        return redirect(app)
    return render(request, "shared/form.html", {"form": form, "title": "New application", "back_url": "/apps/"})

@login_required
def app_edit(request, pk):
    app = get_object_or_404(MobileApp, pk=pk)
    form = MobileAppForm(request.POST or None, instance=app)
    if request.method == "POST" and form.is_valid():
        app = form.save(); log_event(request, "app.update", f"Updated {app.name}", app)
        messages.success(request, "Application updated.")
        return redirect(app)
    return render(request, "shared/form.html", {"form": form, "title": f"Edit {app.name}", "back_url": app.get_absolute_url()})

@login_required
def app_detail(request, pk):
    app = get_object_or_404(MobileApp.objects.prefetch_related("localizations", "assets", "releases__builds", "submissions"), pk=pk)
    metrics = {}
    from django.db.models import Sum
    for row in app.metrics.values("metric").annotate(total=Sum("value")):
        metrics[row["metric"]] = float(row["total"] or 0)
    return render(request, "publisher/app_detail.html", {"app": app, "metrics": metrics, "jobs": app.jobs.all()[:8], "issues": app.technical_issues.exclude(status="resolved")[:6]})

@login_required
def localization_create(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    form = LocalizationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False); obj.app = app; obj.save()
        messages.success(request, "Localization added.")
        return redirect(app)
    return render(request, "shared/form.html", {"form": form, "title": f"Add localization · {app.name}", "back_url": app.get_absolute_url()})

@login_required
def localization_edit(request, pk):
    obj = get_object_or_404(AppLocalization, pk=pk)
    form = LocalizationForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Localization updated."); return redirect(obj.app)
    return render(request, "shared/form.html", {"form": form, "title": f"Edit {obj.locale}", "back_url": obj.app.get_absolute_url()})

@login_required
def asset_create(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    form = AssetForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False); obj.app = app; obj.save(); messages.success(request, "Asset uploaded."); return redirect(app)
    return render(request, "shared/form.html", {"form": form, "title": f"Upload asset · {app.name}", "back_url": app.get_absolute_url()})

@login_required
@require_POST
def asset_delete(request, pk):
    obj = get_object_or_404(AppAsset, pk=pk); app = obj.app
    obj.file.delete(save=False); obj.delete(); messages.success(request, "Asset removed.")
    return redirect(app)

@login_required
def release_create(request, app_pk):
    app = get_object_or_404(MobileApp, pk=app_pk)
    initial = {"source_branch": app.default_branch}
    form = ReleaseForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        release = form.save(commit=False); release.app = app; release.save()
        if app.supports_android: Build.objects.create(release=release, platform="android")
        if app.supports_ios: Build.objects.create(release=release, platform="ios")
        log_event(request, "release.create", f"Created {release}", release)
        messages.success(request, "Release created with platform build records.")
        return redirect(release)
    return render(request, "shared/form.html", {"form": form, "title": f"New release · {app.name}", "back_url": app.get_absolute_url()})

@login_required
def release_detail(request, pk):
    release = get_object_or_404(Release.objects.select_related("app").prefetch_related("builds", "jobs", "submissions"), pk=pk)
    readiness = evaluate_release(release)
    return render(request, "publisher/release_detail.html", {"release": release, "readiness": readiness})

@login_required
@require_POST
def release_action(request, pk, action):
    release = get_object_or_404(Release.objects.select_related("app", "app__google_account", "app__apple_account"), pk=pk)
    app = release.app
    if action == "check":
        release.readiness_snapshot = evaluate_release(release); release.status = "ready" if release.readiness_snapshot["ready"] else "checking"; release.save(update_fields=["readiness_snapshot", "status", "updated_at"])
        messages.success(request, f"Readiness: {release.readiness_snapshot['passed']} passed, {release.readiness_snapshot['errors']} errors, {release.readiness_snapshot['warnings']} warnings.")
    elif action in {"build_android", "build_ios"}:
        platform = "android" if action.endswith("android") else "ios"
        build = release.builds.filter(platform=platform).first() or Build.objects.create(release=release, platform=platform)
        build.status = "queued"; build.logs = ""; build.save(update_fields=["status", "logs", "updated_at"])
        enqueue_job(action, app=app, release=release, build=build, agent=True, platform="linux" if platform == "android" else "macos")
        release.status = "building"; release.save(update_fields=["status", "updated_at"])
        messages.success(request, f"{platform.title()} build queued for an available agent.")
    elif action == "upload_apple":
        build = release.builds.filter(platform="ios", status="succeeded").first()
        if not build: messages.error(request, "A successful iOS build is required.")
        else:
            enqueue_job("upload_apple", app=app, release=release, build=build, agent=True, platform="macos")
            messages.success(request, "App Store upload queued for a macOS agent.")
    elif action in {"upload_google", "submit_google", "submit_apple"}:
        build = release.builds.filter(platform="android" if "google" in action else "ios", status="succeeded").first()
        enqueue_job(action, app=app, release=release, build=build)
        messages.success(request, f"{action.replace('_', ' ').title()} queued.")
    else:
        return HttpResponseBadRequest("Unknown action")
    log_event(request, f"release.{action}", f"Queued {action} for {release}", release)
    return redirect(release)

@login_required
@require_POST
def app_action(request, pk, action):
    app = get_object_or_404(MobileApp, pk=pk)
    mapping = {"sync_repository": "sync_repository", "sync_google": "sync_google_reports", "sync_apple": "sync_apple_reports", "sync_status": "sync_store_status"}
    if action not in mapping: return HttpResponseBadRequest("Unknown action")
    enqueue_job(mapping[action], app=app, payload={"year_month": request.POST.get("year_month", "")})
    messages.success(request, f"{action.replace('_', ' ').title()} queued.")
    return redirect(app)

@login_required
def jobs(request):
    return render(request, "publisher/jobs.html", {"jobs": Job.objects.select_related("app", "release", "build")[:300]})

@login_required
def job_detail(request, pk):
    return render(request, "publisher/job_detail.html", {"job": get_object_or_404(Job.objects.select_related("app", "release", "build"), pk=pk)})

@login_required
@require_POST
def job_retry(request, pk):
    job = get_object_or_404(Job, pk=pk)
    job.status, job.error, job.progress, job.finished_at = "queued", "", 0, None; job.save()
    if not job.available_to_agents: run_job.delay(job.pk)
    messages.success(request, "Job queued again.")
    return redirect("job_detail", pk=job.pk)

@login_required
def agent_list(request):
    return render(request, "publisher/agents.html", {"agents": BuildAgent.objects.all()})

@login_required
def agent_create(request):
    form = BuildAgentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        agent, token = BuildAgent.create_with_token(name=data["name"], platform=data["platform"], enabled=data["enabled"], labels=data.get("labels") or [])
        request.session["new_agent_token"] = token
        return redirect("agent_created", pk=agent.pk)
    return render(request, "shared/form.html", {"form": form, "title": "Register build agent", "back_url": "/apps/agents/"})

@login_required
def agent_created(request, pk):
    agent = get_object_or_404(BuildAgent, pk=pk)
    token = request.session.pop("new_agent_token", None)
    return render(request, "publisher/agent_created.html", {"agent": agent, "token": token})


def _agent_from_request(request):
    token = request.headers.get("X-Agent-Token", "")
    if not token: return None
    return BuildAgent.objects.filter(token_hash=hashlib.sha256(token.encode()).hexdigest(), enabled=True).first()

@csrf_exempt
@require_POST
def agent_claim(request):
    agent = _agent_from_request(request)
    if not agent: return JsonResponse({"error": "unauthorized"}, status=401)
    agent.last_seen_at, agent.hostname, agent.app_version = timezone.now(), request.headers.get("X-Agent-Hostname", ""), request.headers.get("X-Agent-Version", "")
    agent.save(update_fields=["last_seen_at", "hostname", "app_version", "updated_at"])
    allowed = [agent.platform]
    if agent.platform == "universal": allowed = ["linux", "macos"]
    with transaction.atomic():
        job = Job.objects.select_for_update(skip_locked=True).filter(status="queued", available_to_agents=True, required_platform__in=allowed).select_related("app", "release", "build", "app__apple_account").first()
        if not job: return JsonResponse({"job": None})
        job.status, job.started_at, job.progress = "running", timezone.now(), 1; job.save(update_fields=["status", "started_at", "progress", "updated_at"])
        if job.build:
            job.build.status, job.build.agent, job.build.started_at = "claimed", agent, timezone.now(); job.build.save(update_fields=["status", "agent", "started_at", "updated_at"])
        agent.current_job = job; agent.save(update_fields=["current_job", "updated_at"])
    payload = build_agent_payload(job)
    return JsonResponse({"job": {"id": job.pk, "type": job.type, "payload": payload}})


def build_agent_payload(job):
    app, release = job.app, job.release
    payload = {
        "repository_url": app.repository_url, "repository_token": app.get_repository_token(),
        "branch": release.source_branch or app.default_branch, "commit": release.source_commit,
        "framework": app.framework, "version_name": release.version_name, "build_number": release.build_number,
        "package_name": app.package_name, "bundle_id": app.bundle_id, "build_config": app.build_config,
        "callback_base": "/apps/agent-api",
    }
    if job.type == "upload_apple" and app.apple_account and app.apple_account.configured:
        payload["apple"] = {
            "issuer_id": app.apple_account.apple_issuer_id, "key_id": app.apple_account.apple_key_id,
            "private_key": app.apple_account.get_credentials().get("private_key", ""),
        }
        if job.build and job.build.artifact: payload["artifact_url"] = job.build.artifact.url
    return payload

@csrf_exempt
@require_POST
def agent_log(request, job_pk):
    agent = _agent_from_request(request); job = get_object_or_404(Job, pk=job_pk)
    if not agent or agent.current_job_id != job.pk: return JsonResponse({"error": "unauthorized"}, status=401)
    data = json.loads(request.body or b"{}")
    job.append_log(data.get("line", "")); job.progress = min(99, int(data.get("progress", job.progress))); job.save(update_fields=["progress", "updated_at"])
    if job.build:
        job.build.logs = job.logs; job.build.status = "running"; job.build.save(update_fields=["logs", "status", "updated_at"])
    return JsonResponse({"ok": True})

@csrf_exempt
@require_POST
def agent_complete(request, job_pk):
    agent = _agent_from_request(request); job = get_object_or_404(Job.objects.select_related("build", "release"), pk=job_pk)
    if not agent or agent.current_job_id != job.pk: return JsonResponse({"error": "unauthorized"}, status=401)
    status = request.POST.get("status", "failed")
    artifact = request.FILES.get("artifact")
    metadata = json.loads(request.POST.get("metadata", "{}") or "{}")
    error = request.POST.get("error", "")
    if job.build:
        build = job.build
        if artifact:
            build.artifact.save(artifact.name, artifact, save=False)
            build.artifact_size = artifact.size
            h = hashlib.sha256()
            for chunk in artifact.chunks(): h.update(chunk)
            build.artifact_checksum = h.hexdigest()
        build.external_build_id = metadata.get("external_build_id", build.external_build_id)
        build.metadata = metadata
        build.status = "succeeded" if status == "succeeded" else "failed"
        build.finished_at = timezone.now(); build.logs = job.logs + ("\n" + error if error else "")
        build.save()
    job.status = "succeeded" if status == "succeeded" else "failed"; job.progress = 100 if status == "succeeded" else job.progress; job.finished_at = timezone.now(); job.error = error; job.result = metadata; job.save()
    agent.current_job = None; agent.last_seen_at = timezone.now(); agent.save(update_fields=["current_job", "last_seen_at", "updated_at"])
    if job.release:
        builds = job.release.builds.all()
        if builds.exists() and all(b.status == "succeeded" for b in builds): job.release.status = "uploaded" if job.type == "upload_apple" else "ready"
        elif any(b.status == "failed" for b in builds): job.release.status = "failed"
        job.release.save(update_fields=["status", "updated_at"])
    return JsonResponse({"ok": True})
