from __future__ import annotations

import io

from django.test import SimpleTestCase
from PIL import Image

from scripts.google_play_cloud_operation import normalize_store_asset


class GooglePlayAssetNormalizationTests(SimpleTestCase):
    @staticmethod
    def image_bytes(size, mode="RGB", color=None):
        if color is None:
            color = (35, 105, 210, 255) if mode == "RGBA" else (35, 105, 210)
        image = Image.new(mode, size, color)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def test_feature_graphic_is_normalized_to_exact_play_dimensions(self):
        content = self.image_bytes((1200, 1200), mode="RGBA")

        normalized, content_type, warning = normalize_store_asset("featureGraphic", content)

        with Image.open(io.BytesIO(normalized)) as result:
            self.assertEqual(result.size, (1024, 500))
            self.assertEqual(result.mode, "RGB")
        self.assertEqual(content_type, "image/png")
        self.assertIn("1024×500", warning)

    def test_icon_is_normalized_to_rgba_512_square(self):
        content = self.image_bytes((900, 600), mode="RGB")

        normalized, content_type, warning = normalize_store_asset("icon", content)

        with Image.open(io.BytesIO(normalized)) as result:
            self.assertEqual(result.size, (512, 512))
            self.assertEqual(result.mode, "RGBA")
        self.assertLessEqual(len(normalized), 1024 * 1024)
        self.assertEqual(content_type, "image/png")
        self.assertIn("512×512", warning)

    def test_screenshots_are_not_modified(self):
        content = self.image_bytes((1080, 1920))

        normalized, content_type, warning = normalize_store_asset("phoneScreenshots", content)

        self.assertEqual(normalized, content)
        self.assertIsNone(content_type)
        self.assertIsNone(warning)
