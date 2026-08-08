from pathlib import Path
import py_compile
import sys

import requests
from django.test import SimpleTestCase


class CustomCloudAgentSyntaxTests(SimpleTestCase):
    @property
    def root(self):
        return Path(__file__).resolve().parents[2]

    def test_custom_cloud_agents_compile(self):
        for relative in (
            "agents/custom_cloud_linux.py",
            "agents/custom_cloud_macos.py",
            "agents/cloud_linux.py",
        ):
            py_compile.compile(str(self.root / relative), doraise=True)

    def test_linux_agent_retries_only_transient_poll_errors(self):
        agents = str(self.root / "agents")
        if agents not in sys.path:
            sys.path.insert(0, agents)
        from cloud_linux import CloudLinuxAgent

        transient = requests.Response()
        transient.status_code = 502
        auth = requests.Response()
        auth.status_code = 403

        self.assertTrue(CloudLinuxAgent._transient_poll_error(requests.HTTPError(response=transient)))
        self.assertTrue(CloudLinuxAgent._transient_poll_error(requests.Timeout("temporary timeout")))
        self.assertFalse(CloudLinuxAgent._transient_poll_error(requests.HTTPError(response=auth)))
        self.assertFalse(CloudLinuxAgent._transient_poll_error(RuntimeError("build/config failure")))
