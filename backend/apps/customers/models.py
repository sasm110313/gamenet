from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class Customer(models.Model):
    """A person who buys play time. Edge rows are authoritative; cloud rows are
    read-only replicas maintained by the sync projections."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge_id = models.UUIDField(db_index=True)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=24, blank=True, db_index=True)
    group = models.ForeignKey(
        "customer_groups.CustomerGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customers",
    )
    credit_limit = models.PositiveIntegerField(default=settings.DEFAULT_CREDIT_LIMIT)
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)
    is_replica = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["edge_id", "phone"],
                condition=~models.Q(phone=""),
                name="customers_unique_phone_per_edge",
            )
        ]
        indexes = [models.Index(fields=["edge_id", "is_active", "full_name"])]

    def __str__(self) -> str:
        return self.full_name
