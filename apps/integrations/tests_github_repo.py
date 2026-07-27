from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase, override_settings

from .github_repo import GitHubRepoClient


class GitHubRepoClientFallbackTests(SimpleTestCase):
    @override_settings(PUBLISHER_GITHUB_TOKEN="global-valid")
    @patch("apps.integrations.github_repo.requests.get")
    def test_expired_app_token_retries_with_global_token(self, get):
        bad = Mock(ok=False, status_code=401, text='{"message":"Bad credentials"}')
        good = Mock(ok=True, status_code=200)
        good.json.return_value = {"tree": []}
        get.side_effect = [bad, good]

        client = GitHubRepoClient("https://github.com/example/private-app.git", "app-expired")
        result = client.tree("main")

        self.assertEqual(result, [])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer app-expired")
        self.assertEqual(get.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer global-valid")
        self.assertEqual(client.token, "global-valid")

    @override_settings(PUBLISHER_GITHUB_TOKEN="")
    @patch("apps.integrations.github_repo.requests.get")
    def test_public_repository_retries_anonymously_after_bad_token(self, get):
        bad = Mock(ok=False, status_code=401, text='{"message":"Bad credentials"}')
        good = Mock(ok=True, status_code=200)
        good.json.return_value = {"tree": [{"path": "README.md", "type": "blob"}]}
        get.side_effect = [bad, good]

        client = GitHubRepoClient("https://github.com/example/public-app", "expired")
        tree = client.tree("main")

        self.assertEqual(tree[0]["path"], "README.md")
        self.assertNotIn("Authorization", get.call_args_list[1].kwargs["headers"])
        self.assertEqual(client.auth_source, "anonymous")

    @override_settings(PUBLISHER_GITHUB_TOKEN="also-invalid")
    @patch("apps.integrations.github_repo.requests.get")
    def test_evidence_failure_returns_empty_evidence_instead_of_breaking_compliance(self, get):
        get.side_effect = [
            Mock(ok=False, status_code=401, text='{"message":"Bad credentials"}'),
            Mock(ok=False, status_code=401, text='{"message":"Bad credentials"}'),
            Mock(ok=False, status_code=404, text='{"message":"Not Found"}'),
        ]
        client = GitHubRepoClient("https://github.com/example/private-app", "expired")

        evidence = client.evidence_files("main")

        self.assertEqual(evidence, {})
        self.assertIn("GitHub API 404", client.last_error)
        self.assertEqual(get.call_count, 3)
