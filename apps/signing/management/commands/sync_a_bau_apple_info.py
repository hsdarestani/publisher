from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp


APP_SLUG = "a-bau"


class Command(BaseCommand):
    help = "Sync A+Bau app-level App Store localization (name, subtitle and privacy URLs)."

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=APP_SLUG).select_related("apple_account").first()
        if not app:
            raise CommandError("A+Bau is not registered in Publisher.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+Bau Apple account is not configured.")

        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        infos = client.request("GET", f"/apps/{record['id']}/appInfos?limit=10").get("data", [])
        if not infos:
            raise CommandError("Apple appInfo record not found for A+Bau.")

        editable_states = {
            "PREPARE_FOR_SUBMISSION",
            "READY_FOR_REVIEW",
            "DEVELOPER_REJECTED",
            "METADATA_REJECTED",
            "REJECTED",
        }
        app_info = next(
            (
                item for item in infos
                if (item.get("attributes", {}).get("appStoreState") or item.get("attributes", {}).get("state")) in editable_states
            ),
            infos[0],
        )

        for loc in app.localizations.all():
            existing = client.request(
                "GET",
                f"/appInfos/{app_info['id']}/appInfoLocalizations?filter[locale]={loc.locale}&limit=1",
            ).get("data", [])
            attrs = {
                "name": loc.title,
                "subtitle": loc.subtitle or None,
                "privacyPolicyUrl": app.privacy_policy_url or None,
                "privacyChoicesUrl": "https://kayi.smarbiz.sbs/konto-loeschen/",
            }
            attrs = {key: value for key, value in attrs.items() if value}
            if existing:
                item_id = existing[0]["id"]
                body = {
                    "data": {
                        "type": "appInfoLocalizations",
                        "id": item_id,
                        "attributes": attrs,
                    }
                }
                client.request("PATCH", f"/appInfoLocalizations/{item_id}", data=json.dumps(body))
                self.stdout.write(self.style.SUCCESS(f"apple_app_info_{loc.locale}=updated"))
            else:
                body = {
                    "data": {
                        "type": "appInfoLocalizations",
                        "attributes": {"locale": loc.locale, **attrs},
                        "relationships": {
                            "appInfo": {"data": {"type": "appInfos", "id": app_info["id"]}}
                        },
                    }
                }
                client.request("POST", "/appInfoLocalizations", data=json.dumps(body))
                self.stdout.write(self.style.SUCCESS(f"apple_app_info_{loc.locale}=created"))

        self.stdout.write(self.style.SUCCESS("apple_store_name=A+Bau"))
