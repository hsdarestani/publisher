from pathlib import Path
import py_compile

from django.test import SimpleTestCase


class CustomCloudAgentSyntaxTests(SimpleTestCase):
    def test_custom_cloud_agents_compile(self):
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "agents/custom_cloud_linux.py",
            "agents/custom_cloud_macos.py",
        ):
            py_compile.compile(str(root / relative), doraise=True)
