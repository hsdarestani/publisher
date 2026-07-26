from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from apps.publisher.models import MobileApp
from .models import MetricPoint

class ReportTests(TestCase):
    def test_report_page_aggregates_metrics(self):
        user = get_user_model().objects.create_user("r", password="pass12345")
        self.client.login(username="r", password="pass12345")
        app = MobileApp.objects.create(name="Metrics", slug="metrics")
        MetricPoint.objects.create(app=app, store="google", date=date.today(), metric="downloads", value=12)
        response = self.client.get(reverse("reports"), {"app": app.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "12")
