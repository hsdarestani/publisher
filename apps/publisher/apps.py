from django.apps import AppConfig


class PublisherConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.publisher"
    verbose_name = "Publisher"

    def ready(self):
        from . import signals  # noqa: F401
