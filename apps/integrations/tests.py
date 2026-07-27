from django.test import TestCase

from apps.publisher.forms import StoreAccountForm
from apps.publisher.models import StoreAccount


class StoreAccountCredentialFormTests(TestCase):
    def google_json(self, email="publisher@example-project.iam.gserviceaccount.com"):
        return {
            "type": "service_account",
            "project_id": "example-project",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
            "client_email": email,
            "client_id": "123456789",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

    def test_edit_form_shows_safe_identity_but_never_private_key(self):
        account = StoreAccount.objects.create(provider="google", name="Google", organization="A+")
        account.set_credentials(self.google_json())
        account.save()

        form = StoreAccountForm(instance=account)

        self.assertIn("publisher@example-project.iam.gserviceaccount.com", form["stored_credentials"].value())
        self.assertIn("project: example-project", form["stored_credentials"].value())
        self.assertIsNone(form["credentials_json"].value())
        self.assertNotIn("BEGIN PRIVATE KEY", form.as_p())
        self.assertIn("intentionally stays empty", form.fields["credentials_json"].help_text)

    def test_blank_credentials_keep_existing_encrypted_json(self):
        account = StoreAccount.objects.create(provider="google", name="Google", organization="A+")
        original = self.google_json()
        account.set_credentials(original)
        account.save()
        original_blob = account.credential_blob

        form = StoreAccountForm(
            data={
                "provider": "google",
                "name": "Google",
                "organization": "A+ Solution GmbH",
                "enabled": "on",
                "google_bucket_id": "",
                "apple_issuer_id": "",
                "apple_key_id": "",
                "apple_team_id": "",
                "apple_vendor_number": "",
                "credentials_json": "",
                "apple_private_key": "",
            },
            instance=account,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.credential_blob, original_blob)
        self.assertEqual(saved.get_credentials()["client_email"], original["client_email"])

    def test_replacement_json_is_validated_and_resets_test_status(self):
        account = StoreAccount.objects.create(
            provider="google",
            name="Google",
            organization="A+",
            status="connected",
            last_error="old",
        )
        account.set_credentials(self.google_json())
        account.save()

        replacement = self.google_json("new@example-project.iam.gserviceaccount.com")
        import json

        form = StoreAccountForm(
            data={
                "provider": "google",
                "name": "Google",
                "organization": "A+ Solution GmbH",
                "enabled": "on",
                "google_bucket_id": "",
                "apple_issuer_id": "",
                "apple_key_id": "",
                "apple_team_id": "",
                "apple_vendor_number": "",
                "credentials_json": json.dumps(replacement),
                "apple_private_key": "",
            },
            instance=account,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.credential_identity, replacement["client_email"])
        self.assertEqual(saved.status, "not_tested")
        self.assertEqual(saved.last_error, "")

    def test_invalid_google_json_is_rejected_before_save(self):
        import json

        form = StoreAccountForm(
            data={
                "provider": "google",
                "name": "Google",
                "organization": "A+",
                "enabled": "on",
                "google_bucket_id": "",
                "apple_issuer_id": "",
                "apple_key_id": "",
                "apple_team_id": "",
                "apple_vendor_number": "",
                "credentials_json": json.dumps({"type": "service_account", "client_email": "wrong@example.com"}),
                "apple_private_key": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("project_id", str(form.errors))
        self.assertIn("private_key", str(form.errors))
