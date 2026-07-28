from __future__ import annotations

import argparse
import io
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2 import service_account
from PIL import Image, ImageFilter, ImageOps


SCOPE = "https://www.googleapis.com/auth/androidpublisher"
API_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"
UPLOAD_BASE = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3"
RESAMPLE = Image.Resampling.LANCZOS
TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


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


def _retry_delay(attempt: int) -> int:
    return min(2**attempt, 16)


def require_with_retry(request_call, action, *, attempts=5, parse_json=True):
    """Retry safe/idempotent Google Play requests on transient edge failures."""
    for attempt in range(1, attempts + 1):
        response = request_call()
        if response.ok or response.status_code not in TRANSIENT_HTTP_STATUSES or attempt == attempts:
            return require(response, action, parse_json=parse_json)
        delay = _retry_delay(attempt)
        print(
            f"{action} returned transient HTTP {response.status_code}; "
            f"retrying attempt {attempt + 1}/{attempts} in {delay}s."
        )
        time.sleep(delay)
    raise RuntimeError(f"{action} failed after {attempts} attempts.")


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


def _png_bytes(image):
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=9)
    return output.getvalue()


def _flatten_rgba(image, background=(245, 247, 250)):
    rgba = image.convert("RGBA")
    flattened = Image.new("RGB", rgba.size, background)
    flattened.paste(rgba, mask=rgba.getchannel("A"))
    return flattened


def normalize_store_asset(image_type, content):
    """Return Play-compliant bytes, content type and an optional audit message."""
    if image_type not in {"featureGraphic", "icon"}:
        return content, None, None

    try:
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            original_size = image.size
            original_mode = image.mode

            if image_type == "featureGraphic":
                target = (1024, 500)
                rgba = image.convert("RGBA")
                flat = _flatten_rgba(rgba)
                if original_size == target:
                    normalized = flat
                else:
                    background = ImageOps.fit(flat, target, method=RESAMPLE).filter(
                        ImageFilter.GaussianBlur(radius=22)
                    )
                    foreground = ImageOps.contain(rgba, target, method=RESAMPLE)
                    canvas = background.convert("RGBA")
                    offset = (
                        (target[0] - foreground.width) // 2,
                        (target[1] - foreground.height) // 2,
                    )
                    canvas.alpha_composite(foreground, dest=offset)
                    normalized = canvas.convert("RGB")
                output = _png_bytes(normalized)
                message = None
                if original_size != target or original_mode not in {"RGB", "P"}:
                    message = (
                        f"Feature graphic automatically normalized from {original_size[0]}×{original_size[1]} "
                        f"({original_mode}) to Google Play's required 1024×500 RGB PNG without stretching."
                    )
                return output, "image/png", message

            target = (512, 512)
            rgba = image.convert("RGBA")
            if original_size == target:
                normalized = rgba
            else:
                foreground = ImageOps.contain(rgba, target, method=RESAMPLE)
                normalized = Image.new("RGBA", target, (0, 0, 0, 0))
                offset = (
                    (target[0] - foreground.width) // 2,
                    (target[1] - foreground.height) // 2,
                )
                normalized.alpha_composite(foreground, dest=offset)
            output = _png_bytes(normalized)
            if len(output) > 1024 * 1024:
                raise RuntimeError(
                    "Normalized Google Play icon exceeds the 1 MB limit. Use a simpler 512×512 source icon."
                )
            message = None
            if original_size != target or original_mode != "RGBA":
                message = (
                    f"App icon automatically normalized from {original_size[0]}×{original_size[1]} "
                    f"({original_mode}) to Google Play's required 512×512 RGBA PNG."
                )
            return output, "image/png", message
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not decode {image_type} image: {exc}") from exc


def download_asset(asset):
    response = requests.get(asset["url"], timeout=120)
    require(response, f"Download asset {asset.get('name') or asset['url']}", parse_json=False)
    content_type = response.headers.get("content-type", "application/octet-stream").split(";")[0]
    content, normalized_type, normalization_warning = normalize_store_asset(
        asset.get("image_type", ""), response.content
    )
    return {
        **asset,
        "content": content,
        "content_type": normalized_type or content_type,
        "normalization_warning": normalization_warning,
    }


def upload_image_response(session, package_name, edit_id, locale, image_type, asset):
    return session.post(
        f"{UPLOAD_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}/listings/{q(locale)}/{q(image_type)}",
        params={"uploadType": "media"},
        data=asset["content"],
        headers={"Content-Type": asset["content_type"]},
        timeout=300,
    )


def replace_image_group(session, package_name, edit_id, locale, image_type, assets, *, attempts=5):
    """Atomically retry an image group after transient Google upload failures.

    A failed upload may have reached Google's backend even when the client receives
    HTTP 500. Each retry therefore clears the whole image type again before
    uploading the ordered group, preventing duplicate screenshots or graphics.
    """
    ordered_assets = sorted(assets, key=lambda item: item.get("sort_order", 0))
    clear_url = (
        f"{API_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}"
        f"/listings/{q(locale)}/{q(image_type)}"
    )

    for attempt in range(1, attempts + 1):
        clear_response = session.delete(clear_url, timeout=60)
        if not clear_response.ok:
            if clear_response.status_code in TRANSIENT_HTTP_STATUSES and attempt < attempts:
                delay = _retry_delay(attempt)
                print(
                    f"Clear {image_type} for {locale} returned transient HTTP "
                    f"{clear_response.status_code}; retrying group attempt {attempt + 1}/{attempts} in {delay}s."
                )
                time.sleep(delay)
                continue
            require(clear_response, f"Clear {image_type} for {locale}")

        retry_group = False
        for asset in ordered_assets:
            response = upload_image_response(session, package_name, edit_id, locale, image_type, asset)
            if response.ok:
                require(response, f"Upload {image_type}")
                continue
            if response.status_code in TRANSIENT_HTTP_STATUSES and attempt < attempts:
                delay = _retry_delay(attempt)
                print(
                    f"Upload {image_type} returned transient HTTP {response.status_code}; "
                    f"clearing and retrying the complete {locale}/{image_type} group "
                    f"({attempt + 1}/{attempts}) in {delay}s."
                )
                time.sleep(delay)
                retry_group = True
                break
            require(response, f"Upload {image_type}")

        if retry_group:
            continue
        return len(ordered_assets)

    raise RuntimeError(f"Upload {image_type} failed after {attempts} attempts.")


def apply_payload(payload, credentials):
    package_name = payload["package_name"]
    prepared_groups = {}
    warnings = []
    for asset in payload.get("assets", []):
        prepared = download_asset(asset)
        prepared_groups.setdefault((asset["locale"], asset["image_type"]), []).append(prepared)
        if prepared.get("normalization_warning"):
            warnings.append(prepared["normalization_warning"])

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
            require_with_retry(
                lambda listing=listing, body=body: session.put(
                    f"{API_BASE}/applications/{q(package_name)}/edits/{q(edit_id)}/listings/{q(listing['locale'])}",
                    json=body,
                    timeout=60,
                ),
                f"Update listing {listing['locale']}",
            )
            listing_count += 1

        image_count = 0
        for (locale, image_type), assets in prepared_groups.items():
            image_count += replace_image_group(
                session,
                package_name,
                edit_id,
                locale,
                image_type,
                assets,
            )

        require_with_retry(
            lambda: session.post(
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
    except Exception:
        delete_edit(session, package_name, edit_id)
        raise

    data_safety_applied = False
    data_safety_error = ""
    data_safety_csv = payload.get("data_safety_csv", "").strip()
    if data_safety_csv:
        try:
            require_with_retry(
                lambda: session.post(
                    f"{API_BASE}/applications/{q(package_name)}/dataSafety",
                    json={"safetyLabels": data_safety_csv},
                    timeout=120,
                ),
                "Apply Data Safety",
            )
            data_safety_applied = True
        except Exception as exc:
            data_safety_error = str(exc)
            warnings.append(
                "Store listing and images were committed successfully, but Data Safety was not applied: "
                + data_safety_error
            )

    return {
        "success": True,
        "package_name": package_name,
        "listing_count": listing_count,
        "image_count": image_count,
        "data_safety_applied": data_safety_applied,
        "data_safety_error": data_safety_error,
        "warnings": warnings,
        "edit": committed,
        "executor": "github-actions",
    }


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
