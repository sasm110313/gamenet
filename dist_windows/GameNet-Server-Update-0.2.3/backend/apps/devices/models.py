from __future__ import annotations

import secrets
import string

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7

# Avoid 0/O and 1/I: these codes get read aloud and retyped at the counter.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class RegistrationCode(models.Model):
    """One-time pairing code an administrator reads to a new client machine."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    code = models.CharField(max_length=16, unique=True)
    label = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.OneToOneField(
        "clients.ClientDevice", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def generate_code(length: int = 8) -> str:
        return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))

    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"{self.code} {'(used)' if self.used_at else ''}"
