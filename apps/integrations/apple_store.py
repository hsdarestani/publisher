from __future__ import annotations
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import jwt
import requests
from .base import IntegrationError, IntegrationNotConfigured, IntegrationResult

BASE_URL = "https://api.appstoreconnect.apple.com/v1"

class AppleStoreClient:
    def __init__(self, store_account):
        self.account = store_account
        self.private_key = store_account.get_credentials().get("private_key", "")
        if not (store_account.apple_issuer_id and store_account.apple_key_id and self.private_key):
            raise IntegrationNotConfigured("Apple Issuer ID, Key ID and private key are required.")

    def token(self):
        now = datetime.now(timezone.utc)
        payload = {"iss": self.account.apple_issuer_id, "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=19)).timestamp()), "aud": "appstoreconnect-v1"}
        return jwt.encode(payload, self.private_key, algorithm="ES256", headers={"kid": self.account.apple_key_id, "typ": "JWT"})

    def request(self, method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers.update({"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"})
        response = requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=90, **kwargs)
        if not response.ok:
            raise IntegrationError(f"Apple API {response.status_code}: {response.text[:1000]}")
        if response.status_code == 204:
            return {}
        return response.json()

    def test(self) -> IntegrationResult:
        try:
            data = self.request("GET", "/apps?limit=1")
            return IntegrationResult(True, "Apple App Store Connect credentials are valid.", {"apps": len(data.get("data", []))})
        except Exception as exc:
            return IntegrationResult(False, str(exc))

    def find_app(self, bundle_id: str):
        data = self.request("GET", f"/apps?filter[bundleId]={bundle_id}&limit=1")
        values = data.get("data", [])
        if not values:
            raise IntegrationError(f"No App Store Connect app record found for {bundle_id}.")
        return values[0]

    def create_version(self, app_id: str, version: str, platform="IOS"):
        body = {"data": {"type": "appStoreVersions", "attributes": {"platform": platform, "versionString": version}, "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
        return self.request("POST", "/appStoreVersions", data=json.dumps(body))["data"]

    def find_editable_version(self, app_id: str, version: str):
        data = self.request("GET", f"/apps/{app_id}/appStoreVersions?filter[versionString]={version}&limit=10")
        return next(iter(data.get("data", [])), None)

    def list_versions(self, app_id: str, platform="IOS", limit=50):
        # Apple supports platform filtering and limit on this relationship, but no
        # sort query parameter. Preserve the API's returned order and select an
        # editable draft explicitly in ensure_version().
        return self.request(
            "GET",
            f"/apps/{app_id}/appStoreVersions?filter[platform]={platform}&limit={limit}",
        ).get("data", [])

    def update_version_string(self, version_id: str, version: str):
        body = {
            "data": {
                "type": "appStoreVersions",
                "id": version_id,
                "attributes": {"versionString": version},
            }
        }
        return self.request(
            "PATCH",
            f"/appStoreVersions/{version_id}",
            data=json.dumps(body),
        )["data"]

    def ensure_version(self, app_id, version):
        exact = self.find_editable_version(app_id, version)
        if exact:
            return exact

        # The first App Store Connect record is sometimes created manually before
        # Publisher runs (for example 1.0 while the signed binary is 1.0.0).
        # Apple only permits one editable version per platform at this stage, and
        # versionString is writable. Align that existing draft to the binary's
        # CFBundleShortVersionString instead of trying to create a second version.
        editable_states = {
            "PREPARE_FOR_SUBMISSION",
            "READY_FOR_REVIEW",
            "DEVELOPER_REJECTED",
            "METADATA_REJECTED",
            "REJECTED",
        }
        for item in self.list_versions(app_id):
            attrs = item.get("attributes", {})
            state = attrs.get("appStoreState") or attrs.get("appVersionState")
            if state in editable_states:
                return self.update_version_string(item["id"], version)

        return self.create_version(app_id, version)

    def _write_localization(self, method, path, body, *, retry_without_whats_new=True):
        try:
            return self.request(method, path, data=json.dumps(body))["data"]
        except IntegrationError as exc:
            # App Store Connect exposes `whatsNew` on version localizations, but
            # some version states (notably a first version being prepared) reject
            # editing that attribute while allowing the rest of the localization.
            # Keep all valid metadata and retry only when Apple explicitly names
            # this field as the state blocker.
            message = str(exc)
            if (
                retry_without_whats_new
                and "whatsNew" in message
                and "cannot be edited at this time" in message
            ):
                data = body.get("data", {})
                attributes = dict(data.get("attributes", {}))
                attributes.pop("whatsNew", None)
                retry_body = {
                    "data": {
                        **data,
                        "attributes": attributes,
                    }
                }
                return self._write_localization(
                    method,
                    path,
                    retry_body,
                    retry_without_whats_new=False,
                )
            raise

    def set_localization(self, version_id, loc):
        existing = self.request("GET", f"/appStoreVersions/{version_id}/appStoreVersionLocalizations?filter[locale]={loc.locale}&limit=1").get("data", [])
        attrs = {
            "description": loc.full_description or None,
            "keywords": loc.keywords or None,
            "marketingUrl": loc.app.marketing_url or None,
            "promotionalText": loc.promotional_text or None,
            "supportUrl": loc.app.support_url or None,
            "whatsNew": loc.release_notes or None,
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        if existing:
            item_id = existing[0]["id"]
            body = {"data": {"type": "appStoreVersionLocalizations", "id": item_id, "attributes": attrs}}
            return self._write_localization("PATCH", f"/appStoreVersionLocalizations/{item_id}", body)
        body = {"data": {"type": "appStoreVersionLocalizations", "attributes": {"locale": loc.locale, **attrs}, "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}}}}
        return self._write_localization("POST", "/appStoreVersionLocalizations", body)

    def attach_build(self, version_id, build_id):
        body = {"data": {"type": "builds", "id": str(build_id)}}
        return self.request("PATCH", f"/appStoreVersions/{version_id}/relationships/build", data=json.dumps(body))

    def set_build_uses_non_exempt_encryption(self, build_id, uses_non_exempt_encryption: bool):
        body = {
            "data": {
                "type": "builds",
                "id": str(build_id),
                "attributes": {
                    "usesNonExemptEncryption": bool(uses_non_exempt_encryption),
                },
            }
        }
        return self.request(
            "PATCH",
            f"/builds/{build_id}",
            data=json.dumps(body),
        )["data"]

    def list_builds(self, app_id, build_number=None, limit=50):
        query = f"filter[app]={app_id}&limit={limit}&sort=-uploadedDate"
        if build_number:
            query += f"&filter[version]={build_number}"
        return self.request("GET", f"/builds?{query}").get("data", [])

    def wait_for_build(self, app_id, build_number, timeout=1800, interval=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            builds = self.list_builds(app_id, build_number)
            for item in builds:
                state = item.get("attributes", {}).get("processingState")
                if state == "VALID": return item
                if state in {"FAILED", "INVALID"}: raise IntegrationError(f"Apple build processing failed: {item}")
            time.sleep(interval)
        raise IntegrationError("Timed out waiting for Apple build processing.")

    def set_review_details(self, version_id, app, contact=None):
        existing = self.request("GET", f"/appStoreVersions/{version_id}/appStoreReviewDetail").get("data")
        attrs = {
            "demoAccountName": app.review_username or None,
            "demoAccountPassword": app.get_review_password() or None,
            "demoAccountRequired": app.requires_login,
            "notes": app.review_notes or None,
        }
        if contact:
            attrs.update(contact)
        attrs = {k: v for k, v in attrs.items() if v not in (None, "")}
        if existing:
            body = {"data": {"type": "appStoreReviewDetails", "id": existing["id"], "attributes": attrs}}
            return self.request("PATCH", f"/appStoreReviewDetails/{existing['id']}", data=json.dumps(body))["data"]
        body = {"data": {"type": "appStoreReviewDetails", "attributes": attrs, "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}}}}
        return self.request("POST", "/appStoreReviewDetails", data=json.dumps(body))["data"]

    def list_review_submissions(self, app_id, state):
        """List review submissions in one Apple state for safe retry handling."""
        return self.request(
            "GET",
            f"/apps/{app_id}/reviewSubmissions?filter[state]={state}&limit=200",
        ).get("data", [])

    def list_review_submission_items(self, submission_id):
        """List submission items with their App Store version relationship."""
        return self.request(
            "GET",
            f"/reviewSubmissions/{submission_id}/items?fields[reviewSubmissionItems]=state,appStoreVersion&include=appStoreVersion&limit=200",
        ).get("data", [])

    @staticmethod
    def _item_targets_version(item, version_id):
        relationship = (
            item.get("relationships", {})
            .get("appStoreVersion", {})
            .get("data")
        )
        return bool(relationship) and str(relationship.get("id")) == str(version_id)

    def cancel_review_submission(self, submission_id):
        body = {
            "data": {
                "type": "reviewSubmissions",
                "id": str(submission_id),
                "attributes": {"canceled": True},
            }
        }
        return self.request(
            "PATCH",
            f"/reviewSubmissions/{submission_id}",
            data=json.dumps(body),
        )["data"]

    def _review_submission_matches(self, submission, version_id):
        items = self.list_review_submission_items(submission["id"])
        item = next(
            (item for item in items if self._item_targets_version(item, version_id)),
            None,
        )
        return item, items

    def submit_version(self, app_id, version_id):
        """Submit a version idempotently without leaking review-submission slots.

        App Store Connect keeps a READY_FOR_REVIEW submission when final review
        eligibility fails. Repeatedly POSTing a new reviewSubmission then leaks
        Apple's finite concurrent-submission slots. Reuse the draft that already
        contains this version, cancel only duplicate drafts for the same version,
        and treat a matching WAITING_FOR_REVIEW/IN_REVIEW submission as success.
        """
        for state in ("WAITING_FOR_REVIEW", "IN_REVIEW"):
            for submission in self.list_review_submissions(app_id, state):
                item, _ = self._review_submission_matches(submission, version_id)
                if item:
                    return {
                        "submission": submission,
                        "item": item,
                        "reused": True,
                        "already_submitted": True,
                    }

        ready_matches = []
        empty_ready = []
        for submission in self.list_review_submissions(app_id, "READY_FOR_REVIEW"):
            item, items = self._review_submission_matches(submission, version_id)
            if item:
                ready_matches.append((submission, item))
            elif not items:
                # A previous failure between ReviewSubmission creation and item
                # creation can leave an empty draft consuming concurrency. Empty
                # READY drafts are safe to cancel; never touch unrelated items.
                empty_ready.append(submission)

        for submission in empty_ready:
            self.cancel_review_submission(submission["id"])

        if ready_matches:
            submission, item = ready_matches[0]
            for duplicate, _ in ready_matches[1:]:
                self.cancel_review_submission(duplicate["id"])
        else:
            body = {"data": {"type": "reviewSubmissions", "attributes": {}, "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
            submission = self.request("POST", "/reviewSubmissions", data=json.dumps(body))["data"]
            item_body = {"data": {"type": "reviewSubmissionItems", "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission["id"]}},
                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}},
            }}}
            item = self.request("POST", "/reviewSubmissionItems", data=json.dumps(item_body))["data"]

        submit_body = {"data": {"type": "reviewSubmissions", "id": submission["id"], "attributes": {"submitted": True}}}
        final = self.request("PATCH", f"/reviewSubmissions/{submission['id']}", data=json.dumps(submit_body))["data"]
        return {
            "submission": final,
            "item": item,
            "reused": bool(ready_matches),
            "cancelled_duplicates": max(0, len(ready_matches) - 1) + len(empty_ready),
        }

    def ensure_analytics_request(self, app_id, access_type="ONGOING"):
        existing = self.request("GET", f"/apps/{app_id}/analyticsReportRequests?limit=10").get("data", [])
        for item in existing:
            if item.get("attributes", {}).get("accessType") == access_type:
                return item
        body = {"data": {"type": "analyticsReportRequests", "attributes": {"accessType": access_type}, "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
        return self.request("POST", "/analyticsReportRequests", data=json.dumps(body))["data"]

    def analytics_reports(self, request_id, category=None):
        path = f"/analyticsReportRequests/{request_id}/reports?limit=200"
        if category: path += f"&filter[category]={category}"
        return self.request("GET", path).get("data", [])

    def download_analytics_instances(self, report_id):
        instances = self.request("GET", f"/analyticsReports/{request_id}/instances?limit=200").get("data", [])
        rows = []
        for instance in instances:
            segments = self.request("GET", f"/analyticsReportInstances/{instance['id']}/segments?limit=200").get("data", [])
            for segment in segments:
                url = segment.get("attributes", {}).get("url")
                if not url: continue
                response = requests.get(url, timeout=120)
                response.raise_for_status()
                rows.extend(self._parse_segment(response.content))
        return rows

    @staticmethod
    def _parse_segment(content: bytes):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                values = []
                for name in archive.namelist():
                    if name.endswith((".csv", ".tsv")):
                        text = archive.read(name).decode("utf-8-sig")
                        import csv
                        dialect = csv.excel_tab if "\t" in text.splitlines()[0] else csv.excel
                        values.extend(csv.DictReader(io.StringIO(text), dialect=dialect))
                return values
        except zipfile.BadZipFile:
            text = content.decode("utf-8-sig", errors="replace")
            import csv
            dialect = csv.excel_tab if text and "\t" in text.splitlines()[0] else csv.excel
            return list(csv.DictReader(io.StringIO(text), dialect=dialect))

    def upload_screenshot(self, localization_id, screenshot_set_id, file_path, asset_type="appScreenshots"):
        path = Path(file_path)
        body = {"data": {"type": "appScreenshots", "attributes": {"fileName": path.name, "fileSize": path.stat().st_size}, "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": screenshot_set_id}}}}}
        reserved = self.request("POST", "/appScreenshots", data=json.dumps(body))["data"]
        operations = reserved.get("attributes", {}).get("uploadOperations", [])
        with path.open("rb") as handle:
            for op in operations:
                handle.seek(op["offset"])
                chunk = handle.read(op["length"])
                headers = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
                response = requests.request(op["method"], op["url"], headers=headers, data=chunk, timeout=180)
                response.raise_for_status()
        commit = {"data": {"type": "appScreenshots", "id": reserved["id"], "attributes": {"uploaded": True, "sourceFileChecksum": self._md5(path)}}}
        return self.request("PATCH", f"/appScreenshots/{reserved['id']}", data=json.dumps(commit))["data"]

    @staticmethod
    def _md5(path):
        import hashlib
        digest = hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()
