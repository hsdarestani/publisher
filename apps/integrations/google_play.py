from __future__ import annotations
import csv
import io
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession, Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.cloud import storage
from .base import IntegrationError, IntegrationNotConfigured, IntegrationResult

logger = logging.getLogger(__name__)
PUBLISH_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
REPORT_SCOPE = "https://www.googleapis.com/auth/playdeveloperreporting"
CLOUD_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"

class GooglePlayClient:
    def __init__(self, store_account):
        self.account = store_account
        self.info = store_account.get_credentials()
        if not self.info.get("client_email") or not self.info.get("private_key"):
            raise IntegrationNotConfigured("Google service-account JSON is not configured.")

    def credentials(self, scopes):
        return service_account.Credentials.from_service_account_info(self.info, scopes=scopes)

    def publisher(self):
        return build("androidpublisher", "v3", credentials=self.credentials([PUBLISH_SCOPE]), cache_discovery=False)

    def test(self, package_name: str | None = None) -> IntegrationResult:
        try:
            if package_name:
                response = self.publisher().edits().insert(packageName=package_name, body={}).execute()
                edit_id = response.get("id")
                if edit_id:
                    self.publisher().edits().delete(packageName=package_name, editId=edit_id).execute()
            else:
                # Credential construction and token refresh catches malformed keys without requiring an app.
                self.credentials([PUBLISH_SCOPE]).refresh(GoogleAuthRequest())
            return IntegrationResult(True, "Google Play credentials are valid.")
        except Exception as exc:
            return IntegrationResult(False, str(exc))

    def publish_release(self, app, release, build_obj, localizations: Iterable, assets: Iterable, submit=True):
        if not app.package_name:
            raise IntegrationError("Android package name is missing.")
        if not build_obj.artifact:
            raise IntegrationError("Android build artifact is missing.")
        service = self.publisher()
        edit = service.edits().insert(packageName=app.package_name, body={}).execute()
        edit_id = edit["id"]
        try:
            bundle = service.edits().bundles().upload(
                packageName=app.package_name,
                editId=edit_id,
                media_body=MediaFileUpload(build_obj.artifact.path, mimetype="application/octet-stream", resumable=True),
            ).execute()
            version_code = str(bundle["versionCode"])
            for loc in localizations:
                body = {
                    "title": loc.title,
                    "shortDescription": loc.short_description or loc.subtitle,
                    "fullDescription": loc.full_description,
                    "video": "",
                }
                service.edits().listings().update(packageName=app.package_name, editId=edit_id, language=loc.locale, body=body).execute()
            grouped = {}
            for asset in assets:
                if asset.platform not in {"android", "shared"}:
                    continue
                image_type = self._image_type(asset)
                if not image_type:
                    continue
                grouped.setdefault((asset.locale, image_type), []).append(asset)
            for (locale, image_type), values in grouped.items():
                service.edits().images().deleteall(packageName=app.package_name, editId=edit_id, language=locale, imageType=image_type).execute()
                for asset in sorted(values, key=lambda x: x.sort_order):
                    service.edits().images().upload(
                        packageName=app.package_name, editId=edit_id, language=locale, imageType=image_type,
                        media_body=MediaFileUpload(asset.file.path, resumable=True),
                    ).execute()
            track_body = {"track": release.android_track, "releases": [{
                "name": release.version_name,
                "versionCodes": [version_code],
                "status": "completed" if float(release.android_rollout) >= 1 else "inProgress",
                **({"userFraction": float(release.android_rollout)} if float(release.android_rollout) < 1 else {}),
                "releaseNotes": [{"language": loc.locale, "text": loc.release_notes or release.release_notes[:500]} for loc in localizations if (loc.release_notes or release.release_notes)],
            }]}
            service.edits().tracks().update(packageName=app.package_name, editId=edit_id, track=release.android_track, body=track_body).execute()
            service.edits().validate(packageName=app.package_name, editId=edit_id).execute()
            if submit:
                committed = service.edits().commit(
                    packageName=app.package_name,
                    editId=edit_id,
                    changesInReviewBehavior="ERROR_IF_IN_REVIEW",
                ).execute()
                return {"edit": committed, "bundle": bundle, "version_code": version_code}
            return {"edit_id": edit_id, "bundle": bundle, "version_code": version_code}
        except Exception:
            try:
                service.edits().delete(packageName=app.package_name, editId=edit_id).execute()
            except Exception:
                logger.exception("Could not delete failed Google Play edit")
            raise

    def reviews(self, package_name, max_results=100):
        return self.publisher().reviews().list(packageName=package_name, maxResults=max_results, translationLanguage="en").execute().get("reviews", [])

    def query_vitals(self, package_name: str, metric_set: str, body: dict):
        creds = self.credentials([REPORT_SCOPE])
        session = AuthorizedSession(creds)
        url = f"https://playdeveloperreporting.googleapis.com/v1beta1/apps/{package_name}/{metric_set}:query"
        response = session.post(url, json=body, timeout=60)
        if not response.ok:
            raise IntegrationError(f"Google reporting API: {response.status_code} {response.text[:500]}")
        return response.json()

    def list_error_issues(self, package_name: str, page_size=100):
        creds = self.credentials([REPORT_SCOPE])
        session = AuthorizedSession(creds)
        url = f"https://playdeveloperreporting.googleapis.com/v1beta1/apps/{package_name}/errorIssues:search"
        response = session.post(url, json={"pageSize": page_size}, timeout=60)
        if not response.ok:
            raise IntegrationError(f"Google error issues API: {response.status_code} {response.text[:500]}")
        return response.json()

    def report_rows(self, package_name: str, year_month: str, report_type="installs", dimension="country"):
        bucket_id = self.account.google_bucket_id.strip()
        if not bucket_id:
            raise IntegrationNotConfigured("Google reporting bucket ID is missing.")
        credentials = self.credentials([CLOUD_SCOPE])
        client = storage.Client(credentials=credentials, project=self.info.get("project_id"))
        bucket = client.bucket(bucket_id.replace("gs://", ""))
        prefix_map = {
            "installs": f"stats/installs/installs_{package_name}_{year_month}_{dimension}.csv",
            "crashes": f"stats/crashes/crashes_{package_name}_{year_month}_{dimension}.csv",
            "ratings": f"stats/ratings/ratings_{package_name}_{year_month}_{dimension}.csv",
        }
        blob = bucket.blob(prefix_map[report_type])
        raw = blob.download_as_bytes()
        text = self._decode_report(raw)
        return list(csv.DictReader(io.StringIO(text)))

    @staticmethod
    def _decode_report(raw):
        for encoding in ("utf-16", "utf-8-sig", "utf-8"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _image_type(asset):
        if asset.kind == "icon": return "icon"
        if asset.kind == "feature_graphic": return "featureGraphic"
        if asset.kind == "promo": return "promoGraphic"
        if asset.kind == "screenshot":
            mapping = {
                "phone": "phoneScreenshots", "seven_inch": "sevenInchScreenshots",
                "ten_inch": "tenInchScreenshots", "tv": "tvScreenshots",
                "wear": "wearScreenshots", "chromeos": "chromeosScreenshots",
            }
            return mapping.get(asset.device_type, "phoneScreenshots")
        return None
