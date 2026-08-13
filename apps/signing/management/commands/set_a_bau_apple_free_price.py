from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp


APP_SLUG = "a-bau"
BASE_TERRITORY = "DEU"


class Command(BaseCommand):
    help = "Set A+Bau's App Store base price to the official free price point in Germany."

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=APP_SLUG).select_related("apple_account").first()
        if not app:
            raise CommandError("A+Bau is not registered in Publisher.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+Bau Apple account is not configured.")

        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        apple_app_id = record["id"]

        # Apple's app price-point reference data contains an official 0.0 tier.
        points = client.request(
            "GET",
            f"/apps/{apple_app_id}/appPricePoints?filter[territory]={BASE_TERRITORY}"
            "&fields[appPricePoints]=customerPrice,proceeds,territory&limit=200",
        ).get("data", [])
        free_point = next(
            (
                point
                for point in points
                if float(point.get("attributes", {}).get("customerPrice", "-1")) == 0.0
            ),
            None,
        )
        if not free_point:
            raise CommandError("Apple's free App Price Point was not returned for DEU.")

        # If a current manual free price already exists, leave pricing untouched.
        try:
            schedule = client.request(
                "GET",
                f"/apps/{apple_app_id}/appPriceSchedule?include=manualPrices,baseTerritory"
                "&fields[appPrices]=startDate,endDate,appPricePoint,territory",
            ).get("data")
        except Exception:
            schedule = None

        if schedule:
            schedule_id = schedule["id"]
            manual = client.request(
                "GET",
                f"/appPriceSchedules/{schedule_id}/manualPrices?filter[territory]={BASE_TERRITORY}"
                "&include=appPricePoint&fields[appPricePoints]=customerPrice&limit=200",
            )
            included = {
                item["id"]: item
                for item in manual.get("included", [])
                if item.get("type") == "appPricePoints"
            }
            for price in manual.get("data", []):
                pp_id = (
                    price.get("relationships", {})
                    .get("appPricePoint", {})
                    .get("data", {})
                    .get("id")
                )
                pp = included.get(pp_id, {})
                if float(pp.get("attributes", {}).get("customerPrice", "-1")) == 0.0:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"apple_pricing=already_free territory={BASE_TERRITORY} price_point={pp_id}"
                        )
                    )
                    return

        temp_price_id = "${a-bau-free-price}"
        body = {
            "data": {
                "type": "appPriceSchedules",
                "attributes": {},
                "relationships": {
                    "app": {
                        "data": {"type": "apps", "id": apple_app_id}
                    },
                    "baseTerritory": {
                        "data": {"type": "territories", "id": BASE_TERRITORY}
                    },
                    "manualPrices": {
                        "data": [{"type": "appPrices", "id": temp_price_id}]
                    },
                },
            },
            "included": [
                {
                    "type": "appPrices",
                    "id": temp_price_id,
                    "attributes": {"startDate": None, "endDate": None},
                    "relationships": {
                        "appPricePoint": {
                            "data": {
                                "type": "appPricePoints",
                                "id": free_point["id"],
                            }
                        }
                    },
                }
            ],
        }
        result = client.request(
            "POST", "/appPriceSchedules", data=json.dumps(body)
        )["data"]
        self.stdout.write(
            self.style.SUCCESS(
                f"apple_pricing=free territory={BASE_TERRITORY} schedule={result['id']} price_point={free_point['id']}"
            )
        )
