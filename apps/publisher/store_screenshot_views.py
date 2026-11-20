"""Receive real device screenshots from the scoped Vice Codes GitHub workflow.

No generated marketing mockups, public submission, or mutable account settings.
The original screenshot pixels are converted to an opaque PNG for store support.
"""
import base64
import hashlib
import io
import json

from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from .cloud_auth import github_vice_codes_screenshot_automation
from .models import AppAsset, MobileApp


@csrf_exempt
@require_POST
def receive_vice_codes_screenshot(request):
    if not github_vice_codes_screenshot_automation(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    if len(request.body) > 11_000_000:
        return JsonResponse({"ok": False, "error": "too_large"}, status=413)
    try:
        body = json.loads(request.body)
        platform = body["platform"]
        index = int(body["index"])
        source = str(body["file"])
        data = base64.b64decode(body["png_base64"], validate=True)
    except (ValueError, TypeError, KeyError) as exc:
        return JsonResponse({"ok": False, "error": "invalid_payload"}, status=422)
    if platform not in ("android", "ios") or not 1 <= index <= 6:
        return JsonResponse({"ok": False, "error": "invalid_platform_or_index"}, status=422)
    if len(data) > 8_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return JsonResponse({"ok": False, "error": "not_a_png"}, status=422)
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        width, height = image.size
        if image.format != "PNG" or not (750 <= width <= 2500 and 1300 <= height <= 5000):
            return JsonResponse({"ok": False, "error": "invalid_screenshot_dimensions"}, status=422)
        if height / width < 1.7 or height / width > 2.6:
            return JsonResponse({"ok": False, "error": "invalid_portrait_aspect"}, status=422)
        img = image.convert("RGB")
        normalized = io.BytesIO()
        img.save(normalized, format="PNG", optimize=True)
        data = normalized.getvalue()
    except (UnidentifiedImageError, ValueError, OSError):
        return JsonResponse({"ok": False, "error": "invalid_image"}, status=422)

    app = MobileApp.objects.filter(slug="vice-codes").first()
    if not app:
        return JsonResponse({"ok": False, "error": "app_missing"}, status=404)
    checksum = hashlib.sha256(data).hexdigest()
    existing = AppAsset.objects.filter(
        app=app, kind="screenshot", platform=platform,
        locale="de-DE", sort_order=index,
    ).first()
    if existing:
        if existing.checksum == checksum:
            return JsonResponse({"ok": True, "reused": True, "asset_id": existing.id})
        return JsonResponse(
            {"ok": False, "error": "screenshot_slot_already_occupied", "asset_id": existing.id},
            status=409,
        )

    device_type = "phone" if platform == "android" else ("APP_IPHONE_67" if width >= 1260 else "APP_IPHONE_61")
    asset = AppAsset(
        app=app, kind="screenshot", platform=platform,
        locale="de-DE", device_type=device_type,
        sort_order=index, width=width, height=height,
        checksum=checksum,
    )
    clean_name = f"vice-codes-{platform}-real-device-{index:02d}.png"
    asset.file.save(clean_name, ContentFile(data), save=False)
    asset.save()
    return JsonResponse({
        "ok": True, "reused": False, "asset_id": asset.id,
        "platform": platform, "width": width, "height": height,
        "device_type": device_type, "source": source[:80],
    }, status=201)
