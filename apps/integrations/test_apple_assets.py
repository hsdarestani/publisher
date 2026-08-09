import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from .apple_assets import sync_app_store_screenshots


class AppleScreenshotSyncTests(SimpleTestCase):
    def _asset(self, path, *, locale="de-DE", sort_order=0):
        return SimpleNamespace(
            pk=1,
            kind="screenshot",
            platform="ios",
            locale=locale,
            device_type="APP_IPHONE_65",
            sort_order=sort_order,
            file=SimpleNamespace(path=str(path)),
        )

    def test_matching_complete_screenshot_is_reused_without_upload_or_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "screen-1.png"
            content = b"publisher-screenshot"
            path.write_bytes(content)
            checksum = hashlib.md5(content).hexdigest()

            client = Mock()
            client.set_localization.return_value = {"id": "loc-1"}

            def request(method, request_path, **kwargs):
                if request_path == "/appStoreVersionLocalizations/loc-1/appScreenshotSets?limit=200":
                    return {
                        "data": [
                            {
                                "id": "set-1",
                                "attributes": {"screenshotDisplayType": "APP_IPHONE_65"},
                            }
                        ]
                    }
                if request_path.startswith("/appScreenshotSets/set-1/appScreenshots?"):
                    self.assertIn("sourceFileChecksum", request_path)
                    self.assertIn("assetDeliveryState", request_path)
                    return {
                        "data": [
                            {
                                "id": "shot-1",
                                "attributes": {
                                    "fileName": path.name,
                                    "fileSize": len(content),
                                    "sourceFileChecksum": checksum,
                                    "assetDeliveryState": {"state": "COMPLETE"},
                                },
                            }
                        ]
                    }
                self.fail(f"Unexpected Apple request: {method} {request_path}")

            client.request.side_effect = request
            result = sync_app_store_screenshots(
                client,
                "version-1",
                [SimpleNamespace(locale="de-DE")],
                [self._asset(path)],
                timeout=1,
            )

            self.assertEqual(result["uploaded"], 0)
            self.assertEqual(result["reused"], 1)
            self.assertEqual(result["screenshot_ids"], ["shot-1"])
            client.upload_screenshot.assert_not_called()
            self.assertFalse(
                any(call.args[0] == "DELETE" for call in client.request.call_args_list)
            )

    def test_mismatched_screenshot_is_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "screen-1.png"
            content = b"new-publisher-screenshot"
            path.write_bytes(content)

            client = Mock()
            client.set_localization.return_value = {"id": "loc-1"}
            client.upload_screenshot.return_value = {"id": "shot-new"}

            def request(method, request_path, **kwargs):
                if request_path == "/appStoreVersionLocalizations/loc-1/appScreenshotSets?limit=200":
                    return {
                        "data": [
                            {
                                "id": "set-1",
                                "attributes": {"screenshotDisplayType": "APP_IPHONE_65"},
                            }
                        ]
                    }
                if request_path.startswith("/appScreenshotSets/set-1/appScreenshots?"):
                    return {
                        "data": [
                            {
                                "id": "shot-old",
                                "attributes": {
                                    "fileName": path.name,
                                    "fileSize": 3,
                                    "sourceFileChecksum": "old",
                                    "assetDeliveryState": {"state": "COMPLETE"},
                                },
                            }
                        ]
                    }
                if method == "DELETE" and request_path == "/appScreenshots/shot-old":
                    return {}
                if method == "GET" and request_path.startswith("/appScreenshots/shot-new?"):
                    return {
                        "data": {
                            "id": "shot-new",
                            "attributes": {"assetDeliveryState": {"state": "COMPLETE"}},
                        }
                    }
                self.fail(f"Unexpected Apple request: {method} {request_path}")

            client.request.side_effect = request
            result = sync_app_store_screenshots(
                client,
                "version-1",
                [SimpleNamespace(locale="de-DE")],
                [self._asset(path)],
                timeout=1,
            )

            self.assertEqual(result["uploaded"], 1)
            self.assertEqual(result["reused"], 0)
            client.upload_screenshot.assert_called_once_with(
                "loc-1",
                "set-1",
                str(path),
            )
