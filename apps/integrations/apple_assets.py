from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

from .base import IntegrationError


def _asset_path(asset):
    try:
        return Path(asset.file.path)
    except (NotImplementedError, AttributeError) as exc:
        raise IntegrationError(
            f"App Store screenshot {asset.pk} is not available on local storage for upload."
        ) from exc


def _md5(path: Path):
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _desired_descriptor(asset):
    path = _asset_path(asset)
    return {
        "asset": asset,
        "path": path,
        "fileName": path.name,
        "fileSize": path.stat().st_size,
        "sourceFileChecksum": _md5(path),
    }


def _current_descriptor(item):
    attrs = item.get("attributes", {})
    return (
        attrs.get("fileName"),
        attrs.get("fileSize"),
        (attrs.get("sourceFileChecksum") or "").lower(),
    )


def sync_app_store_screenshots(client, version_id, localizations, assets, *, timeout=240):
    """Synchronize Publisher-managed iOS screenshots idempotently.

    Existing App Store assets are reused when filename, byte size and Apple's
    MD5 `sourceFileChecksum` match the Publisher file. This prevents a retry from
    deleting/re-uploading already-correct screenshots and avoids repeatedly
    waiting for the same media processing operation.
    """

    grouped = defaultdict(list)
    for asset in assets:
        if asset.kind != "screenshot" or asset.platform != "ios":
            continue
        display_type = (asset.device_type or "APP_IPHONE_65").strip().upper()
        if not display_type.startswith("APP_"):
            display_type = "APP_IPHONE_65"
        grouped[(asset.locale, display_type)].append(asset)

    uploaded = []
    reused = []
    waiting = []

    for loc in localizations:
        relevant = [
            (display, values)
            for (locale, display), values in grouped.items()
            if locale == loc.locale
        ]
        if not relevant:
            continue

        localization = client.set_localization(version_id, loc)
        localization_id = localization["id"]
        existing_sets = client.request(
            "GET",
            f"/appStoreVersionLocalizations/{localization_id}/appScreenshotSets?limit=200",
        ).get("data", [])

        for display_type, values in relevant:
            screenshot_set = next(
                (
                    item
                    for item in existing_sets
                    if item.get("attributes", {}).get("screenshotDisplayType") == display_type
                ),
                None,
            )
            if screenshot_set is None:
                body = {
                    "data": {
                        "type": "appScreenshotSets",
                        "attributes": {"screenshotDisplayType": display_type},
                        "relationships": {
                            "appStoreVersionLocalization": {
                                "data": {
                                    "type": "appStoreVersionLocalizations",
                                    "id": localization_id,
                                }
                            }
                        },
                    }
                }
                screenshot_set = client.request(
                    "POST",
                    "/appScreenshotSets",
                    data=json.dumps(body),
                )["data"]
                existing_sets.append(screenshot_set)

            set_id = screenshot_set["id"]
            current = client.request(
                "GET",
                f"/appScreenshotSets/{set_id}/appScreenshots"
                "?fields[appScreenshots]=fileName,fileSize,sourceFileChecksum,assetDeliveryState"
                "&limit=200",
            ).get("data", [])

            desired = [
                _desired_descriptor(asset)
                for asset in sorted(values, key=lambda item: item.sort_order)
            ]
            current_by_descriptor = {
                _current_descriptor(item): item
                for item in current
            }
            desired_keys = [
                (
                    item["fileName"],
                    item["fileSize"],
                    item["sourceFileChecksum"].lower(),
                )
                for item in desired
            ]

            # Exact media match: preserve the existing resources. COMPLETE assets
            # need no work; UPLOAD_COMPLETE assets only need their existing IDs
            # polled until Apple finishes asynchronous processing.
            if len(current) == len(desired) and all(key in current_by_descriptor for key in desired_keys):
                for key in desired_keys:
                    existing = current_by_descriptor[key]
                    state = (
                        existing.get("attributes", {})
                        .get("assetDeliveryState", {})
                        .get("state", "")
                        .upper()
                    )
                    if state == "FAILED":
                        break
                    reused.append(existing["id"])
                    if state not in {"COMPLETE", "COMPLETED"}:
                        waiting.append(existing["id"])
                else:
                    continue
                # A matching asset is terminally failed: replace the whole set so
                # ordering remains deterministic.
                reused = [item for item in reused if item not in {x["id"] for x in current}]
                waiting = [item for item in waiting if item not in {x["id"] for x in current}]

            for item in current:
                client.request("DELETE", f"/appScreenshots/{item['id']}")

            for descriptor in desired:
                item = client.upload_screenshot(
                    localization_id,
                    set_id,
                    str(descriptor["path"]),
                )
                uploaded.append(item["id"])
                waiting.append(item["id"])

    if waiting:
        _wait_for_screenshots(client, waiting, timeout=timeout)
    return {
        "uploaded": len(uploaded),
        "reused": len(reused),
        "screenshot_ids": uploaded + reused,
    }


def _wait_for_screenshots(client, screenshot_ids, *, timeout):
    pending = set(screenshot_ids)
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        for screenshot_id in list(pending):
            item = client.request(
                "GET",
                f"/appScreenshots/{screenshot_id}?fields[appScreenshots]=assetDeliveryState,fileName,sourceFileChecksum",
            ).get("data", {})
            state_info = item.get("attributes", {}).get("assetDeliveryState", {})
            state = state_info.get("state", "").upper()
            if state in {"COMPLETE", "COMPLETED"}:
                pending.discard(screenshot_id)
            elif state in {"FAILED", "INVALID"}:
                raise IntegrationError(
                    f"App Store screenshot processing failed for {screenshot_id}: {state_info}"
                )
        if pending:
            time.sleep(4)
    if pending:
        raise IntegrationError(
            "Timed out waiting for App Store screenshots to finish processing: "
            + ", ".join(sorted(pending))
        )
