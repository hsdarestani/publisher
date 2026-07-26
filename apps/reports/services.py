from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from django.db import transaction
from django.utils.dateparse import parse_date, parse_datetime
from apps.integrations.google_play import GooglePlayClient
from apps.integrations.apple_store import AppleStoreClient
from apps.integrations.github_repo import GitHubRepoClient
from .models import MetricPoint, TechnicalIssue, RepositorySnapshot, ReportSync


def _decimal(value):
    if value in (None, "", "--"): return Decimal("0")
    try: return Decimal(str(value).replace(",", ""))
    except InvalidOperation: return Decimal("0")


def _date(value):
    return parse_date(str(value)[:10]) or date.today()


def upsert_metric(app, store, day, metric, value, dimensions=None, source=""):
    return MetricPoint.objects.update_or_create(
        app=app, store=store, date=day, metric=metric, dimensions=dimensions or {},
        defaults={"value": _decimal(value), "source": source},
    )


def sync_google_monthly(app, year_month: str, dimensions=("country", "app_version", "os_version")):
    if not app.google_account or not app.google_account.configured:
        return {"skipped": True, "reason": "Google account is not configured."}
    client = GooglePlayClient(app.google_account)
    sync = ReportSync.objects.create(app=app, provider="google_monthly")
    count = 0
    try:
        for dimension in dimensions:
            try:
                rows = client.report_rows(app.package_name, year_month, "installs", dimension)
            except Exception as exc:
                sync.metadata.setdefault("warnings", []).append(f"installs/{dimension}: {exc}")
                continue
            for row in rows:
                dim_value = row.get(dimension.replace("_", " ").title()) or row.get("Country") or row.get("App Version Code") or row.get("Android OS Version") or "all"
                dims = {"dimension": dimension, "value": dim_value}
                mapping = {
                    "downloads": row.get("Daily User Installs") or row.get("Daily Device Installs"),
                    "uninstalls": row.get("Daily User Uninstalls") or row.get("Daily Device Uninstalls"),
                    "active_installs": row.get("Installs on active devices") or row.get("Current User Installs"),
                    "total_installs": row.get("Total User Installs"),
                    "upgrades": row.get("Daily Device Upgrades"),
                }
                for metric, value in mapping.items():
                    if value not in (None, ""):
                        upsert_metric(app, "google", _date(row.get("Date")), metric, value, dims, "google-cloud-report")
                        count += 1
        for dimension in ("app_version", "os_version"):
            try:
                rows = client.report_rows(app.package_name, year_month, "crashes", dimension)
            except Exception as exc:
                sync.metadata.setdefault("warnings", []).append(f"crashes/{dimension}: {exc}")
                continue
            for row in rows:
                dim_value = row.get("App Version Code") or row.get("Android OS Version") or "all"
                dims = {"dimension": dimension, "value": dim_value}
                upsert_metric(app, "google", _date(row.get("Date")), "crashes", row.get("Daily Crashes", 0), dims, "google-cloud-report")
                upsert_metric(app, "google", _date(row.get("Date")), "anrs", row.get("Daily ANRs", 0), dims, "google-cloud-report")
                count += 2
        sync.status, sync.rows_imported = "succeeded", count
    except Exception as exc:
        sync.status, sync.error = "failed", str(exc)
        raise
    finally:
        from django.utils import timezone as djtz
        sync.finished_at = djtz.now(); sync.save()
    return {"rows": count, "warnings": sync.metadata.get("warnings", [])}


def sync_google_issues(app):
    if not app.google_account or not app.google_account.configured:
        return {"skipped": True}
    client = GooglePlayClient(app.google_account)
    data = client.list_error_issues(app.package_name)
    count = 0
    for item in data.get("errorIssues", []):
        attrs = item
        external_id = item.get("name", "")
        fingerprint = external_id or hashlib.sha256(str(item).encode()).hexdigest()
        title = item.get("cause") or item.get("type") or "Android issue"
        severity = "high" if item.get("type") in {"CRASH", "ANR"} else "medium"
        TechnicalIssue.objects.update_or_create(
            app=app, store="google", fingerprint=fingerprint,
            defaults={
                "external_id": external_id, "issue_type": item.get("type", "error"), "title": title[:300],
                "severity": severity, "occurrences": int(item.get("errorReportCount", 0) or 0),
                "affected_users": int(item.get("distinctUsers", 0) or 0),
                "first_seen": parse_datetime(item.get("firstOsVersion", "")) if item.get("firstOsVersion", "").endswith("Z") else None,
                "last_seen": parse_datetime(item.get("lastErrorReportTime", "")), "raw": item,
            },
        )
        count += 1
    return {"issues": count}


def sync_apple_analytics(app):
    if not app.apple_account or not app.apple_account.configured:
        return {"skipped": True, "reason": "Apple account is not configured."}
    client = AppleStoreClient(app.apple_account)
    app_record = client.find_app(app.bundle_id)
    request = client.ensure_analytics_request(app_record["id"])
    reports = client.analytics_reports(request["id"])
    imported = 0
    for report in reports:
        name = report.get("attributes", {}).get("name", "")
        try:
            rows = client.download_analytics_instances(report["id"])
        except Exception:
            continue
        for row in rows:
            day = _date(row.get("Date") or row.get("date"))
            normalized = {str(k).lower().replace(" ", "_"): v for k, v in row.items()}
            mappings = {
                "downloads": normalized.get("total_downloads") or normalized.get("first-time_downloads") or normalized.get("app_units"),
                "redownloads": normalized.get("redownloads"),
                "sessions": normalized.get("sessions"),
                "active_devices": normalized.get("active_devices"),
                "crashes": normalized.get("crashes"),
                "impressions": normalized.get("impressions"),
                "product_page_views": normalized.get("product_page_views"),
            }
            dimensions = {k: v for k, v in normalized.items() if k in {"territory", "platform_version", "device", "app_version", "source_type"} and v}
            for metric, value in mappings.items():
                if value not in (None, ""):
                    upsert_metric(app, "apple", day, metric, value, dimensions, f"apple-analytics:{name}")
                    imported += 1
    return {"rows": imported, "reports": len(reports)}


def sync_repository(app):
    if not app.repository_url:
        return {"skipped": True, "reason": "Repository URL is missing."}
    client = GitHubRepoClient(app.repository_url, app.get_repository_token())
    data = client.sync_summary(app.default_branch)
    parsed_date = parse_datetime(data.get("latest_date") or "")
    app.tech_stack = data["stack"]
    app.latest_commit_sha = data["latest_sha"]
    app.latest_commit_at = parsed_date
    from django.utils import timezone as djtz
    app.last_synced_at = djtz.now()
    app.save(update_fields=["tech_stack", "latest_commit_sha", "latest_commit_at", "last_synced_at", "updated_at"])
    RepositorySnapshot.objects.create(
        app=app, commit_sha=data["latest_sha"], branch=app.default_branch,
        commit_count=len(data["commits"]), stack=data["stack"], commits=data["commits"],
    )
    upsert_metric(app, "github", date.today(), "commits_synced", len(data["commits"]), {}, "github-api")
    return data
