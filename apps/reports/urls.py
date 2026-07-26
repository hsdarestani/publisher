from django.urls import path
from . import views
urlpatterns = [
    path("", views.report_index, name="reports"),
    path("metrics.json", views.metrics_json, name="metrics_json"),
    path("issues/", views.issue_list, name="issues"),
    path("issues/<int:pk>/", views.issue_detail, name="issue_detail"),
]
