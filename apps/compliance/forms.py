from __future__ import annotations

from django import forms

from .models import ComplianceProfile


AGE_CHOICES = [
    ("5 and under", "5 and under"),
    ("6-8", "6–8"),
    ("9-12", "9–12"),
    ("13-15", "13–15"),
    ("16-17", "16–17"),
    ("18 and over", "18 and over"),
]


class ComplianceProfileForm(forms.ModelForm):
    target_age_groups = forms.MultipleChoiceField(
        choices=AGE_CHOICES,
        required=True,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ComplianceProfile
        fields = [
            "primary_locale",
            "support_email",
            "purpose",
            "business_model",
            "has_ads",
            "target_age_groups",
            "app_access",
            "app_access_instructions",
            "account_deletion",
            "account_deletion_url",
            "payment_handling",
            "payment_details",
            "data_safety_template",
        ]
        widgets = {
            "purpose": forms.Textarea(attrs={"rows": 5}),
            "app_access_instructions": forms.Textarea(attrs={"rows": 5}),
            "payment_details": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "account_deletion": (
                "Required when users can create accounts. Choose the real deletion path available to users."
            ),
            "account_deletion_url": (
                "Required when deletion is offered on the web. It must be publicly accessible without logging in."
            ),
            "payment_handling": (
                "Clarifies whether Publisher should declare payment data, purchase history, or an external processor."
            ),
            "payment_details": (
                "Optional provider or implementation note, for example: Stripe Checkout; card data never reaches our servers."
            ),
            "data_safety_template": (
                "Optional but required for direct Data Safety API submission. Export the current CSV template "
                "from Play Console once; Publisher fills and reuses it automatically."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput) and not isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        deletion = cleaned.get("account_deletion")
        deletion_url = cleaned.get("account_deletion_url")
        if deletion == "web" and not deletion_url:
            self.add_error("account_deletion_url", "Enter the public account-deletion URL.")
        payment = cleaned.get("payment_handling")
        details = (cleaned.get("payment_details") or "").strip()
        if payment == "direct" and not details:
            self.add_error("payment_details", "Describe which payment data is handled directly and by which backend/provider.")
        return cleaned


class ComplianceOverrideForm(forms.Form):
    data_practices_json = forms.CharField(widget=forms.Textarea(attrs={"rows": 18, "class": "form-control"}), required=False)
    content_rating_json = forms.CharField(widget=forms.Textarea(attrs={"rows": 12, "class": "form-control"}), required=False)

    def clean_data_practices_json(self):
        return self._json("data_practices_json")

    def clean_content_rating_json(self):
        return self._json("content_rating_json")

    def _json(self, name):
        import json

        value = self.cleaned_data.get(name, "").strip()
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Invalid JSON: {exc}")
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Value must be a JSON object.")
        return parsed
