import json

from apps.integrations.apple_store import AppleStoreClient
from apps.signing.management.commands.provision_aplus_solution_push import Command as PushCommand
from apps.signing.models import IOSProvisioningProfile
from apps.signing.services import ensure_ios_signing


class Command(PushCommand):
    help = "Provision SchichtPro Apple Push Notifications and refresh its App Store profile."

    def handle(self, *args, **options):
        from apps.publisher.models import MobileApp

        app = MobileApp.objects.filter(bundle_id="sbs.smarbiz.schichtpro").first()
        if not app:
            self.stderr.write("SchichtPro is not registered yet; push provisioning skipped.")
            return
        state = self._apple(app, True)
        self.stdout.write(f"schichtpro_apple_push={state}")

    def _apple(self, app, apply=True):
        client = AppleStoreClient(app.apple_account)
        bundle_id = "sbs.smarbiz.schichtpro"
        bundles = client.request("GET", f"/bundleIds?filter[identifier]={bundle_id}&limit=10").get("data", [])
        bundle = next(item for item in bundles if item.get("attributes", {}).get("identifier") == bundle_id)
        capabilities = client.request("GET", f"/bundleIds/{bundle['id']}/bundleIdCapabilities").get("data", [])
        if not any(item.get("attributes", {}).get("capabilityType") == "PUSH_NOTIFICATIONS" for item in capabilities):
            body = {"data": {"type": "bundleIdCapabilities", "attributes": {"capabilityType": "PUSH_NOTIFICATIONS"}, "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle["id"]}}}}}
            client.request("POST", "/bundleIdCapabilities", data=json.dumps(body))
        profile = IOSProvisioningProfile.objects.filter(app=app).first()
        if profile and self._profile_push_state(profile) not in {"production", "development"}:
            try:
                client.request("DELETE", f"/profiles/{profile.apple_profile_id}")
            except Exception:
                pass
            profile.delete()
        profile = ensure_ios_signing(app)
        return f"enabled:profile_{self._profile_push_state(profile)}"
