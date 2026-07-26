from django.urls import path
from . import views
urlpatterns = [
    path("", views.account_list, name="integration_accounts"),
    path("new/", views.account_create, name="integration_create"),
    path("<int:pk>/edit/", views.account_edit, name="integration_edit"),
    path("<int:pk>/test/", views.account_test, name="integration_test"),
]
