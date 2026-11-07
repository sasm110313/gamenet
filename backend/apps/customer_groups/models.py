from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class CustomerGroup(models.Model):
    """A billing group; every member inherits the group's tariff until it changes."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=80)
    tariff = models.ForeignKey(
        "pricing.Tariff", null=True, blank=True, on_delete=models.PROTECT, related_name="groups"
    )
    is_active = models.BooleanField(default=True)
    is_replica = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["edge_id", "name"], name="customer_groups_unique_name"
            )
        ]

    def __str__(self) -> str:
        return self.name
