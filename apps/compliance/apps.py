from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.compliance"
    verbose_name = "Store compliance"

    def ready(self):
        from . import signals  # noqa: F401

        # Views historically regenerated the Google CSV directly when the cloud
        # runner fetched its payload, bypassing the sanitizer used by the task.
        # Bind every view-level generation path to the same strict generator so
        # the reviewed CSV cannot be replaced by stale template answers in transit.
        from . import views
        from .data_safety_sanitize import strict_data_safety_csv

        views.fill_data_safety_template = strict_data_safety_csv
