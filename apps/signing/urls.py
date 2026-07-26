from django.urls import path

from . import views


urlpatterns = [
    path("jobs/<int:job_pk>/credentials/", views.job_credentials, name="android_job_credentials"),
    path("apps/<int:app_pk>/backup/", views.download_backup, name="android_signing_backup"),
]
