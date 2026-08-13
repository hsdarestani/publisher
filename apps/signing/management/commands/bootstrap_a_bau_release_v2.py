from __future__ import annotations

import json

from apps.integrations.apple_store import AppleStoreClient
from apps.signing.management.commands.bootstrap_a_bau_release import Command as ABBauReleaseCommand


APP_ID = "de.kayihaustechnik.app"


class Command(ABBauReleaseCommand):
    help = "Prepare A+Bau Store release with Apple-safe internal Bundle ID naming."

    def _ensure_apple_bundle_id(self, app):
        if not app.apple_account or not app.apple_account.configured:
            return None
        client = AppleStoreClient(app.apple_account)
        data = client.request("GET", f"/bundleIds?filter[identifier]={APP_ID}&limit=10")
        for item in data.get("data", []):
            if item.get("attributes", {}).get("identifier") == APP_ID:
                self.stdout.write("apple_bundle_id=existing")
                return item

        # Apple rejects '+' in the internal Bundle ID resource name. This is not
        # the customer-facing App Store name; App Store metadata remains "A+Bau".
        body = {
            "data": {
                "type": "bundleIds",
                "attributes": {
                    "identifier": APP_ID,
                    "name": "A Bau",
                    "platform": "IOS",
                },
            }
        }
        item = client.request("POST", "/bundleIds", data=json.dumps(body))["data"]
        self.stdout.write(self.style.SUCCESS("apple_bundle_id=registered internal_name=A Bau"))
        return item
