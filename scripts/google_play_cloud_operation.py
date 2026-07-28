from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote

import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2 import service_account


SCOPE = "https://www.googleapis.com/auth/androidpublisher"
API_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"
UPLOAD_BASE = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3"


def q(value):
    return quote(str(value), safe="._-")


def response_detail(response):
    try:
        return response.json()
    except Exception:
        return " ".join(response.text.replace("\n", " ").split())[:1200]


def require(response, action, *, parse_json=True):
    if not response.ok:
        raise RuntimeError(
            f"{action} failed: HTTP {response.status_code} {json.dumps(response_detail(response), ensure_ascii=False)}"
        )
    if not parse_json:
        return response
    return response.json() if response.content else {}


def create_edit(session, package_name):
    return require(
        session.post(f"{API_BASE}/applications/{q(package_name)}/edits", json={}, timeout=60),
        "Create Google Play edit",
    )["id"]


def delete_edit(session, package_name, edit_id):
    try:
        session.delete(
            f"{API_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}",
            timeout=30,
        )
    except Exception:
        pass


def download_asset(asset):
    response = requests.get(asset["url"], timeout=120)
    require(response, f"Download asset {asset.get('name') or asset['url']}", parse_json=False)
    return {
        **asset,
        "content": response.content,
        "content_type": response.headers.get("content-type", "application/octet-stream").split(";")[0],
    }


def upload_image(session, package_name, edit_id, locale, image_type, asset):
    return require(
        session.post(
            f"{UPLOAD_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}/listings/{q(locale)}/{q(image_type)}",
            params={"uploadType": "media"},
            data=asset["content"],
            headers={"Content-Type": asset["content_type"]},
            timeout=300,
        ),
        f"Upload {image_type}",
    )


def apply_payload(payload, credentials):
    package_name = payload["package_name"]
    prepared_groups = {}
    for asset in payload.get("assets", []):
        prepared_groups.setdefault((asset["locale"], asset["image_type"]), []).append(download_asset(asset))

    session = AuthorizedSession(credentials)
    edit_id = create_edit(session, package_name)
    try:
        listing_count = 0
        for listing in payload.get("localizations", []):
            body = {
                "title": listing.get("title", ""),
                "shortDescription": listing.get("short_description", ""),
                "fullDescription": listing.get("full_description", ""),
                "video": listing.get("video", ""),
            }
            require(
                session.put(
                    f"{API_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}/listings/{q(listing['locale'])}",
                    json=body,
                    timeout=60,
                ),
                f"Update listing {listing['locale']}",
            )
            listing_count += 1

        image_count = 0
        for (locale, image_type), assets in prepared_groups.items():
            require(
                session.delete(
                    f"{API_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}/listings/{q(locale)}/{q(image_type)}",
                    timeout=60,
                ),
                f"Clear {image_type} for {locale}",
            )
            for asset in sorted(assets, key=lambda item: item.get("sort_order", 0)):
                upload_image(session, package_name, edit_id, locale, image_type, asset)
                image_count += 1

        require(
            session.post(
                f"{API_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}:validate",
                json={},
                timeout=60,
            ),
            "Validate Google Play edit",
        )
        committed = require(
            session.post(
                f"{API_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}:commit",
                params={"changesInReviewBehavior": "ERROR_IF_IN_REVIEW"},
                json={},
                timeout=60,
            ),
            "Commit Google Play edit",
        )

        data_safety_applied = False
        data_safety_csv = payload.get("data_safety_csv", "").strip()
        if data_safety_csv:
            require(
                session.post(
                    f"{API_BASE}/applications/{q(package_name)}/dataSafety",
                    json={"safetyLabels": data_safety_csv},
                    timeout=120,
                ),
                "Apply Data Safety",
            )
            data_safety_applied = True

        return {
            "success": True,
            "package_name": package_name,
            "listing_count": listing_count,
            "image_count": image_count,
            "data_safety_applied": data_safety_applied,
            "warnings": [],
            "edit": committed,
            "executor": "github-actions",
        }
    except Exception:
        delete_edit(session, package_name, edit_id)
        raise


def callback(url, token, result):
    response = requests.post(
        url,
        params={"token": token},
        json=result,
        timeout=60,
        headers={"User-Agent": "APlus-Publisher-GooglePlay-Cloud/1.0"},
    )
    if not response.ok:
        raise RuntimeError(f"Publisher callback failed: HTTP {response.status_code} {response.text[:800]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-url", required=True)
    parser.add_argument("--callback-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--output", default="google-play-cloud-result.json")
    args = parser.parse_args()

    result = {"success": False, "executor": "github-actions"}
    try:
        raw = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            raise RuntimeError("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is missing.")
        info = json.loads(raw)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
        credentials.refresh(Request())

        payload_response = requests.get(
            args.payload_url,
            params={"token": args.token},
            timeout=60,
            headers={"User-Agent": "APlus-Publisher-GooglePlay-Cloud/1.0"},
        )
        payload = require(payload_response, "Fetch Publisher operation payload")
        result = apply_payload(payload, credentials)
    except Exception as exc:
        result = {
            "success": False,
            "executor": "github-actions",
            "error": str(exc),
        }

    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    callback(args.callback_url, args.token, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
