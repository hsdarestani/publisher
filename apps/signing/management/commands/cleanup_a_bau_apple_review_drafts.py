from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.apple_store import AppleStoreClient
from apps.publisher.models import MobileApp


APP_SLUG = "a-bau"


class Command(BaseCommand):
    help = "Cancel only empty READY_FOR_REVIEW drafts for A+Bau in App Store Connect."

    def handle(self, *args, **options):
        app = MobileApp.objects.filter(slug=APP_SLUG).select_related("apple_account").first()
        if not app:
            raise CommandError("A+Bau is not registered in Publisher.")
        if not app.apple_account or not app.apple_account.configured:
            raise CommandError("A+Bau Apple account is not configured.")

        client = AppleStoreClient(app.apple_account)
        record = client.find_app(app.bundle_id)
        ready = client.list_review_submissions(record["id"], "READY_FOR_REVIEW")
        canceled = 0
        preserved = 0

        for submission in ready:
            submission_id = submission["id"]
            items = client.list_review_submission_items(submission_id)
            if items:
                self.stdout.write(
                    f"preserved_review_submission={submission_id} items={len(items)}"
                )
                preserved += 1
                continue
            result = client.cancel_review_submission(submission_id)
            state = result.get("attributes", {}).get("state", "unknown")
            self.stdout.write(
                f"canceled_empty_review_submission={submission_id} state={state}"
            )
            canceled += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"apple_review_draft_cleanup=done canceled={canceled} preserved={preserved}"
            )
        )
