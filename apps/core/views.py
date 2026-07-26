from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from apps.core.models import AuditEvent
from apps.publisher.models import MobileApp, Release, Job, Submission
from apps.reports.models import MetricPoint, TechnicalIssue


def healthz(request):
    return JsonResponse({"ok": True, "service": "a-plus-publisher"})

@login_required
def dashboard(request):
    since = timezone.now().date() - timedelta(days=30)
    installs = MetricPoint.objects.filter(metric="downloads", date__gte=since).aggregate(v=Sum("value"))["v"] or 0
    context = {
        "apps_count": MobileApp.objects.count(),
        "active_releases": Release.objects.exclude(status__in=["draft", "released", "failed"]).count(),
        "failed_jobs": Job.objects.filter(status="failed").count(),
        "open_issues": TechnicalIssue.objects.exclude(status="resolved").count(),
        "downloads_30d": int(installs),
        "apps": MobileApp.objects.prefetch_related("releases").order_by("name")[:8],
        "jobs": Job.objects.select_related("app", "release").order_by("-created_at")[:8],
        "submissions": Submission.objects.select_related("release", "app").order_by("-updated_at")[:6],
        "audit_events": AuditEvent.objects.select_related("actor")[:8],
    }
    return render(request, "core/dashboard.html", context)
