from __future__ import annotations

import json
import time
from collections import defaultdict

from .base import IntegrationError


def sync_app_store_screenshots(client, version_id, localizations, assets, *, timeout=240):
    """Replace App Store screenshots for Publisher-managed iOS assets.

    Publisher stores the App Store Connect screenshot display type directly in
    AppAsset.device_type (for example APP_IPHONE_65). This avoids guessing a
    device family from image dimensions and keeps the store declaration
    explicit and reviewable.
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
    for loc in localizations:
        relevant = [(display, values) for (locale, display), values in grouped.items() if locale == loc.locale]
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
                    item for item in existing_sets
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
                                "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                            }
                        },
                    }
                }
                screenshot_set = client.request("POST", "/appScreenshotSets", data=json.dumps(body))["data"]
                existing_sets.append(screenshot_set)

            set_id = screenshot_set["id"]
            current = client.request("GET", f"/appScreenshotSets/{set_id}/appScreenshots?limit=200").get("data", [])
            for item in current:
                client.request("DELETE", f"/appScreenshots/{item['id']}")

            for asset in sorted(values, key=lambda item: item.sort_order):
                try:
                    path = asset.file.path
                except (NotImplementedError, AttributeError) as exc:
                    raise IntegrationError(
                        f"App Store screenshot {asset.pk} is not available on local storage for upload."
                    ) from exc
                item = client.upload_screenshot(localization_id, set_id, path)
                uploaded.append(item["id"])

    if uploaded:
        _wait_for_screenshots(client, uploaded, timeout=timeout)
    return {"uploaded": len(uploaded), "screenshot_ids": uploaded}


def _wait_for_screenshots(client, screenshot_ids, *, timeout):
    pending = set(screenshot_ids)
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        for screenshot_id in list(pending):
            item = client.request("GET", f"/appScreenshots/{screenshot_id}").get("data", {})
            state = (
                item.get("attributes", {})
                .get("assetDeliveryState", {})
                .get("state", "")
                .upper()
            )
            if state in {"COMPLETE", "COMPLETED"}:
                pending.discard(screenshot_id)
            elif state in {"FAILED", "INVALID"}:
                raise IntegrationError(f"App Store screenshot processing failed for {screenshot_id}: {item}")
        if pending:
            time.sleep(4)
    if pending:
        raise IntegrationError(
            "Timed out waiting for App Store screenshots to finish processing: " + ", ".join(sorted(pending))
        )
