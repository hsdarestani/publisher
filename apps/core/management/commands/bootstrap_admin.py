import os
import secrets
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Create the first administrator without making deployment depend on credentials."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            return
        email = os.getenv("ADMIN_EMAIL", "").strip() or "admin@publisher.local"
        password = os.getenv("ADMIN_PASSWORD", "").strip() or secrets.token_urlsafe(18)
        username = email.split("@")[0]
        user = User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created administrator: {user.username}"))
        if not os.getenv("ADMIN_PASSWORD", "").strip():
            self.stdout.write(self.style.WARNING(f"Generated initial password: {password}"))
