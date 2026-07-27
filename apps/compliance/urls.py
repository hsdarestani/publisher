from django.urls import path

from . import views


urlpatterns = [
    path("", views.compliance_list, name="compliance_list"),
    path("apps/<int:app_pk>/", views.compliance_detail, name="compliance_detail"),
    path("apps/<int:app_pk>/edit/", views.compliance_edit, name="compliance_edit"),
    path("apps/<int:app_pk>/overrides/", views.compliance_overrides, name="compliance_overrides"),
    path("apps/<int:app_pk>/actions/<str:action>/", views.compliance_action, name="compliance_action"),
    path("apps/<int:app_pk>/download/", views.download_pack, name="compliance_download_pack"),
    path("apps/<int:app_pk>/companion-session/", views.create_companion_session, name="compliance_companion_session"),
    path("runs/<int:pk>/", views.compliance_run, name="compliance_run"),
    path("companion/extension.zip", views.download_companion_extension, name="compliance_companion_extension"),
    path("companion/<uuid:token>/payload.json", views.companion_payload, name="compliance_companion_payload"),
    path("privacy/<slug:slug>/", views.public_privacy_policy, name="public_privacy_policy"),
]
