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
            "data_safety_template",
        ]
        widgets = {
            "purpose": forms.Textarea(attrs={"rows": 5}),
            "app_access_instructions": forms.Textarea(attrs={"rows": 5}),
        }
        help_texts = {
            "data_safety_template": (
                "Optional but required for direct Data Safety API submission. Export the current CSV template "
                "from Play Console once; Publisher fills and reuses it automatically."
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput) and not isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs.setdefault("class", "form-control")


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
