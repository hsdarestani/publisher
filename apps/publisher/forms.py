import json
from django import forms
from .models import MobileApp, AppLocalization, AppAsset, Release, StoreAccount, BuildAgent

class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

class MobileAppForm(StyledModelForm):
    repository_token = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), help_text="Optional. Leave empty to keep the current token.")
    review_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True, attrs={"autocomplete": "off"}),
        help_text="Stored reviewer password. Keep this exact value in Google Play/App Store review access. Change it only when intentionally rotating the real review account.",
    )
    class Meta:
        model = MobileApp
        fields = ["name", "slug", "client_name", "platform", "framework", "status", "package_name", "bundle_id", "google_app_id", "apple_app_id", "repository_url", "default_branch", "repository_token", "privacy_policy_url", "support_url", "marketing_url", "category", "content_rating", "requires_login", "review_username", "review_password", "review_notes", "google_account", "apple_account", "build_config"]
        widgets = {"review_notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self.instance, "pk", None):
            self.fields["review_password"].initial = self.instance.get_review_password()

    def save(self, commit=True):
        obj = super().save(commit=False)
        token = self.cleaned_data.get("repository_token")
        password = self.cleaned_data.get("review_password")
        if token:
            obj.set_repository_token(token)
        if password:
            obj.set_review_password(password)
        if commit:
            obj.save()
            self.save_m2m()
        return obj

class LocalizationForm(StyledModelForm):
    class Meta:
        model = AppLocalization
        fields = ["locale", "title", "subtitle", "short_description", "full_description", "keywords", "promotional_text", "release_notes"]
        widgets = {"full_description": forms.Textarea(attrs={"rows": 10}), "release_notes": forms.Textarea(attrs={"rows": 5})}

class AssetForm(StyledModelForm):
    class Meta:
        model = AppAsset
        fields = ["kind", "platform", "locale", "device_type", "file", "sort_order"]

class ReleaseForm(StyledModelForm):
    class Meta:
        model = Release
        fields = ["version_name", "build_number", "source_branch", "source_commit", "android_track", "android_rollout", "ios_release_type", "auto_submit", "release_notes", "scheduled_at"]
        widgets = {"release_notes": forms.Textarea(attrs={"rows": 6}), "scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

class StoreAccountForm(StyledModelForm):
    stored_credentials = forms.CharField(
        required=False,
        disabled=True,
        label="Stored credential identity",
        help_text="Sensitive key material is encrypted and is never displayed again.",
    )
    credentials_json = forms.CharField(
        required=False,
        label="Credentials JSON",
        widget=forms.Textarea(
            attrs={
                "rows": 10,
                "placeholder": "Paste a NEW Google service-account JSON only when replacing credentials. Leave empty to keep the stored credentials.",
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
    )
    apple_private_key = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 8,
                "placeholder": "Paste a NEW AuthKey_XXXX.p8 only when replacing credentials. Leave empty to keep the stored key.",
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
    )

    class Meta:
        model = StoreAccount
        fields = ["provider", "name", "organization", "enabled", "google_bucket_id", "apple_issuer_id", "apple_key_id", "apple_team_id", "apple_vendor_number", "stored_credentials", "credentials_json", "apple_private_key"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        account = self.instance if getattr(self.instance, "pk", None) else None
        if account and account.configured:
            identity = account.credential_identity or "Encrypted credentials are stored"
            if account.provider == "google" and account.credential_project_id:
                identity = f"{identity} · project: {account.credential_project_id}"
            self.fields["stored_credentials"].initial = f"✓ {identity}"
            self.fields["credentials_json"].help_text = (
                "Existing Google credentials are stored securely. This box intentionally stays empty after Save. "
                "Paste JSON only to replace the current service account."
            )
            self.fields["apple_private_key"].help_text = (
                "Existing Apple private key is stored securely. This box intentionally stays empty after Save. "
                "Paste a .p8 key only to replace it."
            )
        else:
            self.fields["stored_credentials"].initial = "No encrypted credentials are stored yet"
            self.fields["credentials_json"].help_text = "Paste the complete Google service-account JSON object."
            self.fields["apple_private_key"].help_text = "Paste the full App Store Connect .p8 key content."

    def clean_credentials_json(self):
        value = self.cleaned_data.get("credentials_json", "").strip()
        if not value:
            return None
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Invalid JSON: {exc}")
        if not isinstance(data, dict):
            raise forms.ValidationError("Credentials must be a JSON object.")
        if self.cleaned_data.get("provider") == "google":
            required = ["type", "project_id", "client_email", "private_key"]
            missing = [key for key in required if not str(data.get(key, "")).strip()]
            if missing:
                raise forms.ValidationError("Google service-account JSON is missing: " + ", ".join(missing))
            if data.get("type") != "service_account":
                raise forms.ValidationError("Google credentials must have type=service_account.")
            if "BEGIN PRIVATE KEY" not in data.get("private_key", ""):
                raise forms.ValidationError("The Google private_key value is not a valid PEM private key.")
            if not str(data.get("client_email", "")).endswith(".iam.gserviceaccount.com"):
                raise forms.ValidationError("client_email does not look like a Google service-account address.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        replaced = False
        if obj.provider == "google" and self.cleaned_data.get("credentials_json"):
            obj.set_credentials(self.cleaned_data["credentials_json"])
            replaced = True
        elif obj.provider == "apple" and self.cleaned_data.get("apple_private_key"):
            obj.set_credentials({"private_key": self.cleaned_data["apple_private_key"].strip()})
            replaced = True
        if replaced:
            obj.status = "not_tested"
            obj.last_error = ""
            obj.last_tested_at = None
        if commit:
            obj.save()
        return obj

class BuildAgentForm(StyledModelForm):
    class Meta:
        model = BuildAgent
        fields = ["name", "platform", "enabled", "labels"]
        widgets = {"labels": forms.TextInput(attrs={"placeholder": '["flutter", "xcode-18"]'})}
