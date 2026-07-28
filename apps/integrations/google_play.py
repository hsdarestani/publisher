from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import requests
from google.auth.transport.requests import AuthorizedSession, Request as GoogleAuthRequest
from google.cloud import storage
from google.oauth2 import service_account
from googleapiclient.discovery import build

from .base import IntegrationError, IntegrationNotConfigured, IntegrationResult


logger = logging.getLogger(__name__)
PUBLISH_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
REPORT_SCOPE = "https://www.googleapis.com/auth/playdeveloperreporting"
CLOUD_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"


@dataclass
class EditSession:
    session: AuthorizedSession
    api_base: str
    upload_base: str
    endpoint: str
    package_name: str
    edit_id: str
    diagnostics: dict


class GooglePlayClient:
    API_ENDPOINTS = (
        (
            "androidpublisher.googleapis.com",
            "https://androidpublisher.googleapis.com/androidpublisher/v3",
            "https://androidpublisher.googleapis.com/upload/androidpublisher/v3",
        ),
        (
            "www.googleapis.com legacy",
            "https://www.googleapis.com/androidpublisher/v3",
            "https://www.googleapis.com/upload/androidpublisher/v3",
        ),
    )

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
            credentials = self.credentials([PUBLISH_SCOPE])
            credentials.refresh(GoogleAuthRequest())
            token_details = self._token_details(credentials.token)
            scope = token_details.get("scope", "")
            if PUBLISH_SCOPE not in scope.split():
                return IntegrationResult(
                    False,
                    "OAuth token was minted, but the androidpublisher scope is missing.",
                    {"token": self._safe_token_details(token_details)},
                )
            if not package_name:
                return IntegrationResult(
                    True,
                    f"Google OAuth is valid for {self.info.get('client_email')} and includes the Android Publisher scope.",
                    {"token": self._safe_token_details(token_details)},
                )

            edit = self._open_edit(package_name, credentials=credentials, token_details=token_details)
            self._delete_edit(edit)
            service_usage = self._service_usage_probe(credentials)
            return IntegrationResult(
                True,
                (
                    f"Google Play Publishing API is connected for {package_name}. "
                    f"Authenticated as {self.info.get('client_email')} through {edit.endpoint}."
                ),
                {
                    "identity": self.info.get("client_email"),
                    "project_id": self.info.get("project_id"),
                    "endpoint": edit.endpoint,
                    "token": self._safe_token_details(token_details),
                    "service_usage": service_usage,
                    "endpoint_probes": edit.diagnostics.get("endpoint_probes", []),
                },
            )
        except IntegrationError as exc:
            return IntegrationResult(False, str(exc), getattr(exc, "diagnostics", {}))
        except Exception as exc:
            return IntegrationResult(False, f"Google OAuth failed before the Publishing API call: {exc}")

    def apply_store_content(self, app, localizations: Iterable, assets: Iterable):
        """Apply localized listing text and visual assets without uploading a build."""
        if not app.package_name:
            raise IntegrationError("Android package name is missing.")
        edit = self._open_edit(app.package_name)
        warnings = []
        try:
            localization_count = 0
            for loc in localizations:
                body = {
                    "title": loc.title,
                    "shortDescription": loc.short_description or loc.subtitle,
                    "fullDescription": loc.full_description,
                    "video": "",
                }
                self._edit_request(
                    edit,
                    "PUT",
                    f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/listings/{self._q(loc.locale)}",
                    json_body=body,
                )
                localization_count += 1

            grouped = {}
            for asset in assets:
                if asset.platform not in {"android", "shared"}:
                    continue
                image_type = self._image_type(asset)
                if not image_type:
                    continue
                grouped.setdefault((asset.locale, image_type), []).append(asset)
            image_count = 0
            for (locale, image_type), values in grouped.items():
                self._edit_request(
                    edit,
                    "DELETE",
                    f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/listings/{self._q(locale)}/{self._q(image_type)}",
                )
                for asset in sorted(values, key=lambda x: x.sort_order):
                    try:
                        path = Path(asset.file.path)
                    except (NotImplementedError, AttributeError):
                        warnings.append(f"{asset}: storage backend does not expose a local path; image upload skipped.")
                        continue
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    with path.open("rb") as stream:
                        self._upload_request(
                            edit,
                            f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/listings/{self._q(locale)}/{self._q(image_type)}",
                            stream.read(),
                            content_type,
                        )
                    image_count += 1
            self._validate_edit(edit)
            committed = self._commit_edit(edit)
            return {
                "edit": committed,
                "endpoint": edit.endpoint,
                "localizations": localization_count,
                "images": image_count,
                "warnings": warnings,
            }
        except Exception:
            self._safe_delete_edit(edit)
            raise

    def apply_data_safety(self, package_name: str, safety_labels_csv: str):
        if not safety_labels_csv.strip():
            raise IntegrationError("Data Safety CSV is empty.")
        credentials = self.credentials([PUBLISH_SCOPE])
        credentials.refresh(GoogleAuthRequest())
        probes = []
        for endpoint, api_base, _upload_base in self.API_ENDPOINTS:
            session = AuthorizedSession(credentials)
            response = session.post(
                f"{api_base}/applications/{self._q(package_name)}/dataSafety",
                json={"safetyLabels": safety_labels_csv},
                timeout=60,
            )
            probes.append(self._response_summary(endpoint, response))
            if response.ok:
                return response.json() if response.content else {"ok": True, "endpoint": endpoint}
        raise self._api_error("Google rejected the Data Safety submission on every supported endpoint.", probes)

    def publish_release(self, app, release, build_obj, localizations: Iterable, assets: Iterable, submit=True):
        if not app.package_name:
            raise IntegrationError("Android package name is missing.")
        if not build_obj.artifact:
            raise IntegrationError("Android build artifact is missing.")
        edit = self._open_edit(app.package_name)
        try:
            with Path(build_obj.artifact.path).open("rb") as stream:
                bundle = self._upload_request(
                    edit,
                    f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/bundles",
                    stream.read(),
                    "application/octet-stream",
                )
            version_code = str(bundle["versionCode"])
            for loc in localizations:
                body = {
                    "title": loc.title,
                    "shortDescription": loc.short_description or loc.subtitle,
                    "fullDescription": loc.full_description,
                    "video": "",
                }
                self._edit_request(
                    edit,
                    "PUT",
                    f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/listings/{self._q(loc.locale)}",
                    json_body=body,
                )
            grouped = {}
            for asset in assets:
                if asset.platform not in {"android", "shared"}:
                    continue
                image_type = self._image_type(asset)
                if not image_type:
                    continue
                grouped.setdefault((asset.locale, image_type), []).append(asset)
            for (locale, image_type), values in grouped.items():
                self._edit_request(
                    edit,
                    "DELETE",
                    f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/listings/{self._q(locale)}/{self._q(image_type)}",
                )
                for asset in sorted(values, key=lambda x: x.sort_order):
                    path = Path(asset.file.path)
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    with path.open("rb") as stream:
                        self._upload_request(
                            edit,
                            f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/listings/{self._q(locale)}/{self._q(image_type)}",
                            stream.read(),
                            content_type,
                        )
            track_body = {
                "track": release.android_track,
                "releases": [
                    {
                        "name": release.version_name,
                        "versionCodes": [version_code],
                        "status": "completed" if float(release.android_rollout) >= 1 else "inProgress",
                        **({"userFraction": float(release.android_rollout)} if float(release.android_rollout) < 1 else {}),
                        "releaseNotes": [
                            {"language": loc.locale, "text": loc.release_notes or release.release_notes[:500]}
                            for loc in localizations
                            if (loc.release_notes or release.release_notes)
                        ],
                    }
                ],
            }
            self._edit_request(
                edit,
                "PUT",
                f"/applications/{self._q(app.package_name)}/edits/{edit.edit_id}/tracks/{self._q(release.android_track)}",
                json_body=track_body,
            )
            self._validate_edit(edit)
            if submit:
                committed = self._commit_edit(edit)
                try:
                    compliance = app.compliance
                except Exception:
                    compliance = None
                if compliance and compliance.data_safety_csv.strip():
                    self.apply_data_safety(app.package_name, compliance.data_safety_csv)
                return {
                    "edit": committed,
                    "bundle": bundle,
                    "version_code": version_code,
                    "endpoint": edit.endpoint,
                }
            return {
                "edit_id": edit.edit_id,
                "bundle": bundle,
                "version_code": version_code,
                "endpoint": edit.endpoint,
            }
        except Exception:
            self._safe_delete_edit(edit)
            raise

    def reviews(self, package_name, max_results=100):
        credentials = self.credentials([PUBLISH_SCOPE])
        credentials.refresh(GoogleAuthRequest())
        probes = []
        for endpoint, api_base, _upload_base in self.API_ENDPOINTS:
            response = AuthorizedSession(credentials).get(
                f"{api_base}/applications/{self._q(package_name)}/reviews",
                params={"maxResults": max_results, "translationLanguage": "en"},
                timeout=60,
            )
            probes.append(self._response_summary(endpoint, response))
            if response.ok:
                return response.json().get("reviews", [])
        raise self._api_error("Google rejected the reviews request on every supported endpoint.", probes)

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

    def _open_edit(self, package_name: str, credentials=None, token_details=None) -> EditSession:
        credentials = credentials or self.credentials([PUBLISH_SCOPE])
        if not credentials.valid:
            credentials.refresh(GoogleAuthRequest())
        token_details = token_details or self._token_details(credentials.token)
        probes = []
        for endpoint, api_base, upload_base in self.API_ENDPOINTS:
            session = AuthorizedSession(credentials)
            response = session.post(
                f"{api_base}/applications/{self._q(package_name)}/edits",
                json={},
                timeout=60,
            )
            probes.append(self._response_summary(endpoint, response))
            if response.ok:
                body = response.json()
                return EditSession(
                    session=session,
                    api_base=api_base,
                    upload_base=upload_base,
                    endpoint=endpoint,
                    package_name=package_name,
                    edit_id=body["id"],
                    diagnostics={
                        "identity": self.info.get("client_email"),
                        "project_id": self.info.get("project_id"),
                        "token": self._safe_token_details(token_details),
                        "endpoint_probes": probes,
                    },
                )
        service_usage = self._service_usage_probe(credentials)
        diagnostics = {
            "identity": self.info.get("client_email"),
            "project_id": self.info.get("project_id"),
            "package_name": package_name,
            "token": self._safe_token_details(token_details),
            "service_usage": service_usage,
            "endpoint_probes": probes,
        }
        message = self._diagnostic_message(diagnostics)
        error = IntegrationError(message)
        error.diagnostics = diagnostics
        raise error

    def _edit_request(self, edit: EditSession, method: str, path: str, json_body=None, params=None):
        response = edit.session.request(
            method,
            f"{edit.api_base}{path}",
            json=json_body,
            params=params,
            timeout=120,
        )
        if not response.ok:
            raise self._api_error(
                f"Google Play {method} {path} failed through {edit.endpoint}.",
                [self._response_summary(edit.endpoint, response)],
            )
        return response.json() if response.content else {}

    def _upload_request(self, edit: EditSession, path: str, data: bytes, content_type: str):
        response = edit.session.post(
            f"{edit.upload_base}{path}",
            params={"uploadType": "media"},
            data=data,
            headers={"Content-Type": content_type},
            timeout=600,
        )
        if not response.ok:
            raise self._api_error(
                f"Google Play media upload failed through {edit.endpoint}.",
                [self._response_summary(edit.endpoint, response)],
            )
        return response.json() if response.content else {}

    def _validate_edit(self, edit: EditSession):
        return self._edit_request(
            edit,
            "POST",
            f"/applications/{self._q(edit.package_name)}/edits/{edit.edit_id}:validate",
            json_body={},
        )

    def _commit_edit(self, edit: EditSession):
        return self._edit_request(
            edit,
            "POST",
            f"/applications/{self._q(edit.package_name)}/edits/{edit.edit_id}:commit",
            json_body={},
            params={"changesInReviewBehavior": "ERROR_IF_IN_REVIEW"},
        )

    def _delete_edit(self, edit: EditSession):
        response = edit.session.delete(
            f"{edit.api_base}/applications/{self._q(edit.package_name)}/edits/{edit.edit_id}",
            timeout=60,
        )
        if not response.ok:
            raise self._api_error(
                "The test edit was created, but Google rejected cleanup.",
                [self._response_summary(edit.endpoint, response)],
            )

    def _safe_delete_edit(self, edit: EditSession):
        try:
            self._delete_edit(edit)
        except Exception:
            logger.exception("Could not delete failed Google Play edit")

    def _token_details(self, access_token: str):
        try:
            response = requests.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"access_token": access_token},
                timeout=30,
            )
            if response.ok:
                return response.json()
            return {"status": response.status_code, "error": response.text[:500]}
        except Exception as exc:
            return {"error": str(exc)}

    def _service_usage_probe(self, credentials):
        project_id = self.info.get("project_id", "")
        if not project_id:
            return {"state": "unknown", "detail": "project_id is missing"}
        try:
            response = AuthorizedSession(credentials).get(
                f"https://serviceusage.googleapis.com/v1/projects/{quote(project_id, safe='')}/services/androidpublisher.googleapis.com",
                timeout=30,
            )
            if response.ok:
                body = response.json()
                return {"state": body.get("state", "unknown"), "name": body.get("name", "")}
            return {
                "state": "unverified",
                "status": response.status_code,
                "detail": self._response_text(response),
            }
        except Exception as exc:
            return {"state": "unverified", "detail": str(exc)}

    def _diagnostic_message(self, diagnostics: dict) -> str:
        token = diagnostics.get("token", {})
        probes = diagnostics.get("endpoint_probes", [])
        service_usage = diagnostics.get("service_usage", {})
        scope_ok = PUBLISH_SCOPE in str(token.get("scope", "")).split()
        lines = [
            "Google OAuth succeeded, but the Play Publishing API rejected edits.insert.",
            f"Identity: {diagnostics.get('identity')}",
            f"Cloud project: {diagnostics.get('project_id')}",
            f"Package: {diagnostics.get('package_name')}",
            f"Android Publisher OAuth scope: {'present' if scope_ok else 'missing'}",
            f"API enablement probe: {service_usage.get('state', 'unknown')}",
        ]
        for probe in probes:
            lines.append(
                f"Endpoint {probe.get('endpoint')}: HTTP {probe.get('status')} "
                f"({probe.get('content_type') or 'unknown content type'}) · {probe.get('body')}"
            )
        if probes and all(int(item.get("status") or 0) == 403 for item in probes):
            lines.append(
                "Play Console permissions are not the only authorization layer. Since this identity already has app admin access, "
                "the remaining likely causes are API enablement in the exact credential project or Play backend activation for this package."
            )
        return "\n".join(lines)

    @classmethod
    def _api_error(cls, message: str, probes: list[dict]):
        safe = "; ".join(
            f"{item.get('endpoint')}: HTTP {item.get('status')} {item.get('body')}" for item in probes
        )
        error = IntegrationError(f"{message} {safe}".strip())
        error.diagnostics = {"endpoint_probes": probes}
        return error

    @staticmethod
    def _response_summary(endpoint: str, response):
        return {
            "endpoint": endpoint,
            "status": response.status_code,
            "content_type": response.headers.get("content-type", "").split(";")[0],
            "request_id": response.headers.get("x-guploader-uploadid")
            or response.headers.get("x-goog-request-id")
            or response.headers.get("x-request-id")
            or "",
            "body": GooglePlayClient._response_text(response),
        }

    @staticmethod
    def _response_text(response):
        try:
            body = response.json()
            text = json.dumps(body, ensure_ascii=False)
        except Exception:
            text = " ".join(response.text.replace("\n", " ").split())
        return text[:800]

    @staticmethod
    def _safe_token_details(details: dict):
        return {
            "email": details.get("email", ""),
            "scope": details.get("scope", ""),
            "expires_in": details.get("expires_in", ""),
            "access_type": details.get("access_type", ""),
            "verified_email": details.get("verified_email", ""),
        }

    @staticmethod
    def _q(value):
        return quote(str(value), safe="._-")

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
        if asset.kind == "icon":
            return "icon"
        if asset.kind == "feature_graphic":
            return "featureGraphic"
        if asset.kind == "promo":
            return "promoGraphic"
        if asset.kind == "screenshot":
            mapping = {
                "phone": "phoneScreenshots",
                "seven_inch": "sevenInchScreenshots",
                "ten_inch": "tenInchScreenshots",
                "tv": "tvScreenshots",
                "wear": "wearScreenshots",
                "chromeos": "chromeosScreenshots",
            }
            return mapping.get(asset.device_type, "phoneScreenshots")
        return None
