from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp


APP_SLUG = "a-bau"
APPLE_PRIMARY_CATEGORY = "BUSINESS"
APPLE_COPYRIGHT = "2026 A+ Solution GmbH"


class Command(BaseCommand):
    help = "Sync A+Bau app-level localization and required App Store information/version fields."

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=APP_SLUG).select_related("apple_account").first()
        if not app:
            raise CommandError("A+Bau is not registered in Publisher.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+Bau Apple account is not configured.")

        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        apple_app_id = record["id"]
        infos = client.request("GET", f"/apps/{apple_app_id}/appInfos?limit=10").get("data", [])
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

        category_body = {
            "data": {
                "type": "appInfos",
                "id": app_info["id"],
                "relationships": {
                    "primaryCategory": {
                        "data": {
                            "type": "appCategories",
                            "id": APPLE_PRIMARY_CATEGORY,
                        }
                    }
                },
            }
        }
        client.request(
            "PATCH",
            f"/appInfos/{app_info['id']}",
            data=json.dumps(category_body),
        )
        self.stdout.write(self.style.SUCCESS("apple_primary_category=BUSINESS"))

        # Copyright is a required appStoreVersion attribute. Keep every editable
        # A+Bau version populated so a future Publisher retry cannot reach review
        # validation with a null copyright value.
        versions = client.request(
            "GET",
            f"/apps/{apple_app_id}/appStoreVersions?limit=50",
        ).get("data", [])
        patched = 0
        for version in versions:
            attrs = version.get("attributes", {})
            state = attrs.get("appStoreState") or attrs.get("appVersionState")
            if state not in editable_states:
                continue
            if attrs.get("copyright") == APPLE_COPYRIGHT:
                continue
            version_body = {
                "data": {
                    "type": "appStoreVersions",
                    "id": version["id"],
                    "attributes": {"copyright": APPLE_COPYRIGHT},
                }
            }
            client.request(
                "PATCH",
                f"/appStoreVersions/{version['id']}",
                data=json.dumps(version_body),
            )
            patched += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"apple_copyright={APPLE_COPYRIGHT} patched_versions={patched}"
            )
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
