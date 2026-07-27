from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core.views import dashboard, healthz


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("healthz/", healthz, name="healthz"),
    path("", dashboard, name="dashboard"),
    path("apps/", include("apps.publisher.urls")),
    path("integrations/", include("apps.integrations.urls")),
    path("reports/", include("apps.reports.urls")),
    path("signing/", include("apps.signing.urls")),
    path("compliance/", include("apps.compliance.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
