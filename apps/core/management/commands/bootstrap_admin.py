import os
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the first administrator or apply explicitly configured admin credentials."

    def handle(self, *args, **options):
        User = get_user_model()
        configured_email = os.getenv("ADMIN_EMAIL", "").strip()
        configured_password = os.getenv("ADMIN_PASSWORD", "").strip()
        existing = User.objects.filter(is_superuser=True).order_by("pk").first()

        # Explicit credentials are authoritative and can be added after the first
        # deployment. This makes a later GitHub-secret update recover access without
        # requiring shell access or deleting the automatically-created administrator.
        if configured_email and configured_password:
            desired_username = configured_email.split("@")[0]
            user = existing
            if user is None:
                user = User(username=desired_username, email=configured_email)
            elif not User.objects.exclude(pk=user.pk).filter(username=desired_username).exists():
                user.username = desired_username

            user.email = configured_email
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.set_password(configured_password)
            user.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Configured administrator: username={user.username}, email={user.email}"
                )
            )
            return

        if configured_email or configured_password:
            self.stdout.write(
                self.style.WARNING(
                    "Both ADMIN_EMAIL and ADMIN_PASSWORD are required to update administrator access; "
                    "continuing without changing the existing account."
                )
            )

        if existing is not None:
            return

        email = "admin@publisher.local"
        password = secrets.token_urlsafe(18)
        username = "admin"
        user = User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created administrator: {user.username}"))
        self.stdout.write(self.style.WARNING(f"Generated initial password: {password}"))
