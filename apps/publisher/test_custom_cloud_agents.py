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

    def test_custom_shell_build_batches_output_and_flushes_last_lines(self):
        import contextlib
        import io
        import os
        import shlex
        import tempfile
        from unittest.mock import Mock

        agents = str(self.root / "agents")
        if agents not in sys.path:
            sys.path.insert(0, agents)
        from cloud_macos import CloudMacAgent

        agent = object.__new__(CloudMacAgent)
        agent.log = Mock()
        command = shlex.quote(sys.executable) + " -c " + shlex.quote(
            "for i in range(205): print('compiler-line-' + str(i), flush=True)"
        )
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            agent.run_shell(1, command, directory, os.environ.copy(), 20)
        output = "\\n".join(call.args[1] for call in agent.log.call_args_list[1:])
        self.assertEqual(output.splitlines(), ["compiler-line-" + str(i) for i in range(205)])
        self.assertLess(agent.log.call_count, 10)

    def test_custom_shell_failure_flushes_diagnostics_before_raising(self):
        import contextlib
        import io
        import os
        import shlex
        import tempfile
        from unittest.mock import Mock

        agents = str(self.root / "agents")
        if agents not in sys.path:
            sys.path.insert(0, agents)
        from cloud_macos import CloudMacAgent

        agent = object.__new__(CloudMacAgent)
        agent.log = Mock()
        command = shlex.quote(sys.executable) + " -c " + shlex.quote(
            "print('error: compiler rejected input', flush=True); raise SystemExit(3)"
        )
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "exit code 3"):
                agent.run_shell(1, command, directory, os.environ.copy(), 20)
        self.assertIn("error: compiler rejected input", agent.log.call_args.args[1])
