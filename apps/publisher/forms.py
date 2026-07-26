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
    review_password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), help_text="Optional reviewer password; encrypted at rest.")
    class Meta:
        model = MobileApp
        fields = ["name", "slug", "client_name", "platform", "framework", "status", "package_name", "bundle_id", "google_app_id", "apple_app_id", "repository_url", "default_branch", "repository_token", "privacy_policy_url", "support_url", "marketing_url", "category", "content_rating", "requires_login", "review_username", "review_password", "review_notes", "google_account", "apple_account", "build_config"]
        widgets = {"review_notes": forms.Textarea(attrs={"rows": 4})}

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
    credentials_json = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 10, "placeholder": "Paste Google service-account JSON, or leave empty to keep existing credentials."}))
    apple_private_key = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Paste AuthKey_XXXX.p8 content, or leave empty to keep existing credentials."}))
    class Meta:
        model = StoreAccount
        fields = ["provider", "name", "organization", "enabled", "google_bucket_id", "apple_issuer_id", "apple_key_id", "apple_team_id", "apple_vendor_number", "credentials_json", "apple_private_key"]

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
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.provider == "google" and self.cleaned_data.get("credentials_json"):
            obj.set_credentials(self.cleaned_data["credentials_json"])
        elif obj.provider == "apple" and self.cleaned_data.get("apple_private_key"):
            obj.set_credentials({"private_key": self.cleaned_data["apple_private_key"].strip()})
        if commit:
            obj.save()
        return obj

class BuildAgentForm(StyledModelForm):
    class Meta:
        model = BuildAgent
        fields = ["name", "platform", "enabled", "labels"]
        widgets = {"labels": forms.TextInput(attrs={"placeholder": '["flutter", "xcode-18"]'})}
