import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("resolver", Path(__file__).with_name("resolve-release.py"))
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)


class SourceSelection(unittest.TestCase):
    def setUp(self):
        self.pr = {"merged": True, "base": {"ref": resolver.base},
                   "head": {"sha": "a" * 40, "repo": {"full_name": resolver.repo}}}
        self.run = {"id": 31, "run_attempt": 2, "head_sha": "a" * 40, "conclusion": "success",
                    "pull_requests": [{"number": 5}]}
        self.tree = "b" * 40

    def resolve(self):
        values = [self.pr, {"commit": {"tree": {"sha": self.tree}}}, {"tree": {"sha": "b" * 40}},
                  {"workflow_runs": [self.run]}]
        with patch.object(resolver, "api", side_effect=values):
            return resolver.resolve("5")

    def test_uses_exact_green_merged_tree(self):
        self.assertEqual(self.resolve(), "a" * 40)

    def test_unmerged_or_outdated_tree_is_blocked(self):
        self.pr["merged"] = False
        with self.assertRaises(ValueError):
            self.resolve()
        self.pr["merged"] = True
        self.tree = "c" * 40
        with self.assertRaises(ValueError):
            self.resolve()

    def test_failed_or_unrelated_ci_is_blocked(self):
        self.run["conclusion"] = "failure"
        with self.assertRaises(ValueError):
            self.resolve()
        self.run["conclusion"] = "success"
        self.run["pull_requests"] = [{"number": 15}]
        with self.assertRaises(ValueError):
            self.resolve()
