from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class Tariff(models.Model):
    """Hourly price list. Sessions copy the rate at start and are never repriced.

    Edge rows are authoritative; cloud rows are read-only replicas created by
    the ingest projection (`is_replica=True`).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=80)
    hourly_rate = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    is_replica = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["edge_id", "name"], name="pricing_unique_tariff_name"),
            models.CheckConstraint(
                condition=models.Q(hourly_rate__gt=0), name="pricing_tariff_rate_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.hourly_rate:,} تومان/ساعت)"
