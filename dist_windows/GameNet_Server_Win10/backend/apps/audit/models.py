from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.ids import uuid7


class AuditLog(models.Model):
    """Append-only operator audit trail. Financial history lives in the ledger;
    this records who did what to configuration and devices."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["object_type", "object_id", "-created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("AuditLog is append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # pragma: no cover - guard
        raise ValueError("AuditLog is append-only")

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.object_type}:{self.object_id}"
