from django.db import models

from apps.core.crypto import decrypt_json, encrypt_json
from apps.core.models import TimeStampedModel


class AndroidSigningCredential(TimeStampedModel):
    app = models.OneToOneField(
        "publisher.MobileApp",
        related_name="android_signing",
        on_delete=models.CASCADE,
    )
    credential_blob = models.TextField()
    certificate_sha256 = models.CharField(max_length=128, blank=True)
    generated_automatically = models.BooleanField(default=True)

    class Meta:
        ordering = ["app__name"]

    def __str__(self):
        return f"Android upload key · {self.app.name}"

    def set_credentials(self, value: dict) -> None:
        self.credential_blob = encrypt_json(value)

    def get_credentials(self) -> dict:
        return decrypt_json(self.credential_blob)
