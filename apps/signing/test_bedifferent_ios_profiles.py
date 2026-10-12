from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.signing.services import ensure_be_different_ios_signing_bundle


class BeDifferentIOSProfilesTests(SimpleTestCase):
    def test_all_companion_profiles_are_bound_to_current_distribution_certificate(self):
        account = SimpleNamespace()
        app = SimpleNamespace(
            slug="be-different",
            apple_account=account,
            apple_account_id=1,
            bundle_id="com.smarbiz.bedifferent",
        )
        certificate_id = "CERT-20261012-ABCDEF"
        distribution = SimpleNamespace(apple_certificate_id=certificate_id)
        seen = []

        def make_profile(client, credentials, bundle, name):
            seen.append((credentials.apple_certificate_id, bundle["id"], name))
            return {
                "id": "profile-for-" + bundle["id"],
                "attributes": {
                    "name": name,
                    "uuid": "uuid",
                    "profileContent": "dummy-test-only",
                },
            }

        with (
            patch("apps.signing.services.ensure_ios_distribution_signing", return_value=distribution),
            patch("apps.signing.services.AppleStoreClient", return_value=Mock()),
            patch(
                "apps.signing.services._ensure_apple_bundle_id",
                side_effect=lambda client, identifier, display: {"id": identifier},
            ),
            patch("apps.signing.services._ensure_bundle_capability"),
            patch("apps.signing.services._ensure_named_app_store_profile", side_effect=make_profile),
        ):
            cred, material = ensure_be_different_ios_signing_bundle(app)

        self.assertIs(cred, distribution)
        self.assertEqual(len(material), 4)
        self.assertEqual([m["target_name"] for m in material], [
            "BEDIFFERENT", "widget", "watch", "watchwidget",
        ])
        self.assertTrue(all(identifier[:16] in name for _, _, name in seen for identifier in [certificate_id]))
        self.assertTrue(all(m["profile_name"].endswith(certificate_id[:16]) for m in material))

    def test_different_certificate_changes_profile_names(self):
        from apps.signing import services

        def names_for(certificate_id):
            app = SimpleNamespace(
                slug="be-different",
                apple_account=SimpleNamespace(),
                apple_account_id=1,
                bundle_id="com.smarbiz.bedifferent",
            )
            distribution = SimpleNamespace(apple_certificate_id=certificate_id)
            with (
                patch.object(services, "ensure_ios_distribution_signing", return_value=distribution),
                patch.object(services, "AppleStoreClient", return_value=Mock()),
                patch.object(services, "_ensure_apple_bundle_id", side_effect=lambda c, i, d: {"id": i}),
                patch.object(services, "_ensure_bundle_capability"),
                patch.object(
                    services, "_ensure_named_app_store_profile",
                    side_effect=lambda c, d, b, n: {
                        "attributes": {"name": n, "profileContent": "fake", "uuid": "test"}
                    },
                ),
            ):
                return [x["profile_name"] for x in services.ensure_be_different_ios_signing_bundle(app)[1]]

        self.assertNotEqual(names_for("CERT-A-EXAMPLE-AAAA"), names_for("CERT-B-EXAMPLE-BBBB"))
