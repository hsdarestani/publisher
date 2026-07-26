from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from apps.publisher.models import MobileApp
from .models import MetricPoint, TechnicalIssue, RepositorySnapshot

@login_required
def report_index(request):
    apps = MobileApp.objects.all()
    app = None
    app_id = request.GET.get("app")
    if app_id:
        app = get_object_or_404(MobileApp, pk=app_id)
    qs = MetricPoint.objects.all()
    issues = TechnicalIssue.objects.exclude(status="resolved")
    if app:
        qs, issues = qs.filter(app=app), issues.filter(app=app)
    start = timezone.now().date() - timedelta(days=int(request.GET.get("days", 30)))
    qs = qs.filter(date__gte=start)
    totals = {row["metric"]: float(row["total"] or 0) for row in qs.values("metric").annotate(total=Sum("value"))}
    for metric in ("downloads", "active_installs", "sessions", "crashes", "anrs"):
        totals.setdefault(metric, 0.0)
    trend = {}
    for row in qs.values("date", "metric").annotate(total=Sum("value")).order_by("date"):
        trend.setdefault(str(row["date"]), {})[row["metric"]] = float(row["total"] or 0)
    snapshots = RepositorySnapshot.objects.filter(app=app)[:5] if app else RepositorySnapshot.objects.select_related("app")[:10]
    return render(request, "reports/index.html", {"apps": apps, "selected_app": app, "totals": totals, "trend": trend, "issues": issues[:12], "snapshots": snapshots, "days": request.GET.get("days", "30")})

@login_required
def metrics_json(request):
    app = get_object_or_404(MobileApp, pk=request.GET.get("app"))
    days = int(request.GET.get("days", 30))
    start = timezone.now().date() - timedelta(days=days)
    qs = MetricPoint.objects.filter(app=app, date__gte=start)
    values = list(qs.values("date", "metric").annotate(value=Sum("value")).order_by("date"))
    return JsonResponse({"points": [{"date": str(v["date"]), "metric": v["metric"], "value": float(v["value"])} for v in values]})

@login_required
def issue_list(request):
    qs = TechnicalIssue.objects.select_related("app")
    if request.GET.get("app"): qs = qs.filter(app_id=request.GET["app"])
    if request.GET.get("status"): qs = qs.filter(status=request.GET["status"])
    return render(request, "reports/issues.html", {"issues": qs[:200], "apps": MobileApp.objects.all()})

@login_required
def issue_detail(request, pk):
    return render(request, "reports/issue_detail.html", {"issue": get_object_or_404(TechnicalIssue.objects.select_related("app"), pk=pk)})
