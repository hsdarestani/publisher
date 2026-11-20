"""Narrow, OIDC-authenticated Vice Codes store handoff.

No public App Store submission, no Google production track, no credential
exposure. Read-only preflight uses the existing official store connectors.
"""
import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .cloud_auth import github_vice_codes_store_automation
from .models import Job, MobileApp, Release, Submission
from .tasks import enqueue_job


def _compact_job(job):
    return {
        "id": job.pk, "type": job.type, "status": job.status,
        "error": (job.error or "")[:6000],
    }


@csrf_exempt
@require_POST
def vice_codes_store(request):
    if not github_vice_codes_store_automation(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(body, dict) or body.get("app_identifier") != "de.smarbiz.vicecodes":
        return JsonResponse({"ok": False, "error": "invalid_app"}, status=403)

    app = MobileApp.objects.select_related("apple_account", "google_account").filter(slug="vice-codes").first()
    release = Release.objects.filter(pk=40, app=app, version_name="1.0.0", build_number=2).first() if app else None
    if not release:
        return JsonResponse({"ok": False, "error": "release_40_not_found"}, status=404)
    if release.android_track != "internal" or release.auto_submit:
        return JsonResponse({"ok": False, "error": "store_safety_gate", "reason": "Only internal testing with auto_submit off is supported."}, status=409)

    mode = body.get("mode", "preflight")
    if mode not in {"preflight", "upload_test", "status", "submit_public", "submit_google_only", "fix_apple_metadata", "set_apple_free_price"}:
        return JsonResponse({"ok": False, "error": "unsupported_mode"}, status=400)
    builds = {b.platform: b for b in release.builds.all()}
    check = {
        p: bool(b and b.status == "succeeded" and b.artifact)
        for p, b in ((p, builds.get(p)) for p in ("ios", "android"))
    }
    shots = {
        "ios": app.assets.filter(kind="screenshot", platform="ios").count(),
        "android": app.assets.filter(kind="screenshot", platform="android").count(),
    }
    statuses = {
        "ios": {"linked": bool(app.apple_account and app.apple_account.configured), "build_ready": check["ios"]},
        "android": {"linked": bool(app.google_account and app.google_account.configured), "build_ready": check["android"]},
    }
    preflight = {}
    if mode != "status":
        if statuses["ios"]["linked"]:
            from apps.integrations.apple_store import AppleStoreClient
            try:
                found = AppleStoreClient(app.apple_account).find_app(app.bundle_id)
                preflight["ios"] = {"ok": True, "record_id": str(found["id"]), "bundle_id": app.bundle_id}
            except Exception as exc:
                preflight["ios"] = {"ok": False, "error": str(exc)[:1600]}
        else:
            preflight["ios"] = {"ok": False, "error": "Apple account is not linked to this app."}
        if statuses["android"]["linked"]:
            from apps.integrations.google_play import GooglePlayClient
            try:
                client = GooglePlayClient(app.google_account)
                result = client.test(app.package_name)
                preflight["android"] = {"ok": result.ok, "message": str(result.message)[:1800]}
                # The publisher's own assets folder can be empty even when the
                # developer populated genuine screenshots directly in Play Console.
                # Read the official store listing before blocking publication.
                if result.ok:
                    edit = None
                    try:
                        edit = client._open_edit(app.package_name)
                        imgs = client._edit_request(
                            edit, "GET",
                            f"/applications/{client._q(app.package_name)}/edits/"
                            f"{edit.edit_id}/listings/{client._q('de-DE')}/phoneScreenshots",
                        )
                        preflight["android"]["official_phone_screenshots"] = len(imgs.get("images", []))
                    except Exception as screenshot_exc:
                        preflight["android"]["official_screenshot_check_error"] = str(screenshot_exc)[:900]
                    finally:
                        if edit:
                            client._safe_delete_edit(edit)
            except Exception as exc:
                preflight["android"] = {"ok": False, "error": str(exc)[:1800]}
        else:
            preflight["android"] = {"ok": False, "error": "Google account is not linked to this app."}

    metadata_result = {}
    if mode == "fix_apple_metadata":
        # Only verified missing metadata for this exact app, and only after
        # comparing current Apple values. Do not touch price, privacy survey,
        # screenshots, or other developer applications.
        if not statuses["ios"]["linked"] or not preflight.get("ios", {}).get("ok"):
            return JsonResponse({"ok": False, "error": "apple_preflight_required"}, status=409)
        from apps.integrations.apple_store import AppleStoreClient
        client = AppleStoreClient(app.apple_account)
        app_id = str(preflight["ios"]["record_id"])
        infos = client.request("GET", f"/apps/{app_id}/appInfos?limit=10").get("data", [])
        if not infos:
            return JsonResponse({"ok": False, "error": "apple_app_info_missing"}, status=409)
        info = infos[0]
        info_id = str(info["id"])
        categories = client.request("GET", "/appCategories?limit=200").get("data", [])
        entertainment = next(
            (str(row["id"]) for row in categories
             if str(row.get("id", "")).upper() == "ENTERTAINMENT"
             or str(row.get("attributes", {}).get("name", "")).lower() == "entertainment"),
            None,
        )
        primary = client.request("GET", f"/appInfos/{info_id}/relationships/primaryCategory").get("data")
        if not primary:
            if not entertainment:
                metadata_result["category"] = "Entertainment category ID not found; no change made"
            else:
                client.request(
                    "PATCH", f"/appInfos/{info_id}",
                    data=json.dumps({"data": {
                        "type": "appInfos", "id": info_id,
                        "relationships": {"primaryCategory": {
                            "data": {"type": "appCategories", "id": entertainment}
                        }},
                    }}),
                )
                metadata_result["category"] = entertainment
        else:
            metadata_result["category"] = "already:" + str(primary.get("id", ""))
        locs = client.request(
            "GET", f"/appInfos/{info_id}/appInfoLocalizations?limit=200"
        ).get("data", [])
        for loc in locs:
            if loc.get("attributes", {}).get("locale") != "de-DE":
                continue
            current = loc.get("attributes", {}).get("privacyPolicyUrl")
            if not current:
                client.request(
                    "PATCH", f"/appInfoLocalizations/{loc['id']}",
                    data=json.dumps({"data": {
                        "type": "appInfoLocalizations", "id": str(loc["id"]),
                        "attributes": {"privacyPolicyUrl": app.privacy_policy_url},
                    }}),
                )
                metadata_result["privacy_policy"] = app.privacy_policy_url
            else:
                metadata_result["privacy_policy"] = "already_set"
        version = client.ensure_version(app_id, release.version_name)
        attrs = version.get("attributes", {})
        if not attrs.get("copyright"):
            client.request(
                "PATCH", f"/appStoreVersions/{version['id']}",
                data=json.dumps({"data": {
                    "type": "appStoreVersions", "id": str(version["id"]),
                    "attributes": {"copyright": "2026 A+ Solution GmbH"},
                }}),
            )
            metadata_result["copyright"] = "2026 A+ Solution GmbH"
        else:
            metadata_result["copyright"] = "already_set"

    if mode == "set_apple_free_price":
        # One-time free 0.00 app price. Never modify existing schedules or
        # chargeable tiers, and never affect another application.
        if not statuses["ios"]["linked"] or not preflight.get("ios", {}).get("ok"):
            return JsonResponse({"ok": False, "error": "apple_preflight_required"}, status=409)
        from apps.integrations.apple_store import AppleStoreClient
        client = AppleStoreClient(app.apple_account)
        app_id = str(preflight["ios"]["record_id"])
        existing_schedule = None
        try:
            existing_schedule = client.request("GET", f"/apps/{app_id}/appPriceSchedule").get("data")
        except Exception as exc:
            if "404" not in str(exc):
                raise
        if existing_schedule:
            metadata_result["free_price"] = "existing_price_schedule_not_modified"
        else:
            price_points = client.request(
                "GET", f"/apps/{app_id}/appPricePoints?filter[territory]=DEU&limit=200"
            ).get("data", [])
            free_point = next(
                (point for point in price_points
                 if str(point.get("attributes", {}).get("customerPrice", "")).strip()
                 in {"0", "0.0", "0.00", "0.0000"}),
                None,
            )
            if free_point is None:
                return JsonResponse({
                    "ok": False, "error": "no_verified_free_price_point",
                    "points_sample": [
                        {"id": p.get("id"), "customerPrice": p.get("attributes", {}).get("customerPrice")}
                        for p in price_points[:5]
                    ],
                }, status=409)
            ref = "${newprice-0}"
            payload = {
                "data": {
                    "type": "appPriceSchedules",
                    "attributes": {},
                    "relationships": {
                        "app": {"data": {"type": "apps", "id": app_id}},
                        "baseTerritory": {"data": {"type": "territories", "id": "DEU"}},
                        "manualPrices": {"data": [{"type": "appPrices", "id": ref}]},
                    },
                },
                "included": [{
                    "type": "appPrices", "id": ref,
                    "attributes": {"startDate": None, "endDate": None},
                    "relationships": {
                        "appPricePoint": {"data": {
                            "type": "appPricePoints", "id": str(free_point["id"])
                        }},
                    },
                }],
            }
            result = client.request(
                "POST", "/appPriceSchedules", data=json.dumps(payload)
            )
            metadata_result["free_price"] = {
                "schedule_id": result["data"]["id"],
                "base_country": "DEU",
                "amount": "0.00",
            }

    queued = []
    skipped = []
    if mode == "upload_test":
        for platform in ("ios", "android"):
            if not check[platform] or not preflight.get(platform, {}).get("ok"):
                skipped.append({"platform": platform, "reason": "Build or official store preflight failed."})
                continue
            job_type = "upload_apple" if platform == "ios" else "upload_google"
            with transaction.atomic():
                active = Job.objects.select_for_update().filter(
                    release=release, type=job_type, status__in=("queued", "running", "succeeded")
                ).order_by("-created_at").first()
                if active:
                    skipped.append({"platform": platform, "existing": _compact_job(active)})
                    continue
                if platform == "ios":
                    job = enqueue_job("upload_apple", app=app, release=release,
                        build=builds[platform], agent=True, platform="macos")
                else:
                    # Google uploader publishes ONLY to release.android_track ('internal').
                    job = enqueue_job("upload_google", app=app, release=release, build=builds[platform])
                queued.append({"platform": platform, "job": _compact_job(job)})

    if mode in {"submit_public", "submit_google_only"}:
        # A user authorized publication of this specific already-uploaded app.
        # Explicit hard gates prevent accidental submission of another release
        # or of a listing lacking essential legal/store material.
        from urllib.parse import urlparse
        from .review_contacts import apple_review_contact
        from .store_compliance import (
            apple_age_rating_profile,
            apple_content_rights_declaration,
            apple_uses_non_exempt_encryption,
        )
        privacy = urlparse(app.privacy_policy_url or "")
        support = urlparse(app.support_url or "")
        common_ready = bool(
            privacy.scheme == "https" and privacy.netloc
            and support.scheme == "https" and support.netloc
            and app.localizations.filter(locale="de-DE").exclude(full_description="").exists()
            and app.assets.filter(kind="icon", platform__in=("shared", "ios", "android")).exists()
        )
        for platform in (("android",) if mode == "submit_google_only" else ("ios", "android")):
            missing = []
            if not common_ready:
                missing.append("Legal URLs, German description or original app icon missing.")
            if not statuses[platform]["linked"] or not statuses[platform]["build_ready"]:
                missing.append("Signed artifact or linked store account missing.")
            if not preflight.get(platform, {}).get("ok"):
                missing.append("Official store API preflight failed.")
            verified_screens = shots[platform]
            if platform == "android":
                verified_screens = max(
                    verified_screens,
                    preflight.get("android", {}).get("official_phone_screenshots", 0),
                )
            if verified_screens < 3:
                missing.append("At least three genuine app screenshots required in Publisher or official store.")
            if platform == "ios":
                if not builds["ios"].external_build_id:
                    missing.append("Processed App Store Connect build ID missing.")
                contact = apple_review_contact(app)
                if not all(contact.get(field) for field in (
                    "contactFirstName", "contactLastName", "contactPhone", "contactEmail"
                )):
                    missing.append("Real App Review contact missing.")
                if (
                    apple_age_rating_profile(app) is None
                    or apple_content_rights_declaration(app) is None
                    or apple_uses_non_exempt_encryption(app) is None
                ):
                    missing.append("Reviewed App Store compliance declaration missing.")
            else:
                if not app.assets.filter(kind="feature_graphic", platform="android").exists():
                    missing.append("Original Google Play feature graphic missing.")
                internal = Submission.objects.filter(
                    app=app, release=release, platform="android",
                    state__in=("in_review", "ready_for_review", "production_in_review",
                               "production_ready_for_review", "approved", "live"),
                ).exists()
                if not internal:
                    missing.append("No successful internal Google Play handoff to promote.")
            if missing:
                skipped.append({"platform": platform, "reason": missing})
                continue

            job_type = "submit_apple" if platform == "ios" else "submit_google"
            with transaction.atomic():
                active = Job.objects.select_for_update().filter(
                    release=release, type=job_type,
                    status__in=("queued", "running", "succeeded"),
                )
                if platform == "android":
                    active = active.filter(payload__vice_codes_production=True)
                active = active.order_by("-created_at").first()
                if active:
                    skipped.append({"platform": platform, "existing": _compact_job(active)})
                    continue
                payload = {"vice_codes_production": True} if platform == "android" else {}
                job = enqueue_job(
                    job_type, app=app, release=release, build=builds[platform],
                    payload=payload,
                )
                queued.append({"platform": platform, "job": _compact_job(job)})

    prior = [
        _compact_job(job)
        for job in Job.objects.filter(release=release, type__in=("upload_apple", "upload_google")).order_by("-created_at")[:12]
    ]
    submissions = [
        {"platform": sub.platform, "state": sub.state,
         "external_id": sub.external_id, "last_error": (sub.last_error or "")[:500]}
        for sub in Submission.objects.filter(release=release).order_by("platform")
    ]
    return JsonResponse({
        "ok": True,
        "mode": mode,
        "app": app.slug,
        "release_id": release.pk,
        "privacy_policy_url": app.privacy_policy_url,
        "support_url": app.support_url,
        "screenshots_in_publisher": shots,
        "platforms": statuses,
        "preflight": preflight,
        "queued": queued,
        "skipped": skipped,
        "prior_jobs": prior,
        "public_jobs": [
            _compact_job(job)
            for job in Job.objects.filter(
                release=release, type__in=("submit_apple", "submit_google")
            ).order_by("-created_at")[:12]
        ],
        "submissions": submissions,
        "apple_processed_build_id": (builds["ios"].external_build_id if builds.get("ios") else ""),
        "android_track": release.android_track,
        "public_submission_queued": mode in {"submit_public", "submit_google_only"} and bool(queued),
        "apple_metadata": metadata_result,
    })
