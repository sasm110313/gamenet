from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class SessionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class GamingSession(models.Model):
    """A play interval on one device. The edge is the only writer.

    The tariff rate and name are copied into the row at start, so a later price
    change can never alter an active or historical session.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge_id = models.UUIDField(db_index=True)
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="sessions"
    )
    device = models.ForeignKey(
        "clients.ClientDevice", on_delete=models.PROTECT, related_name="sessions"
    )
    status = models.CharField(
        max_length=16, choices=SessionStatus.choices, default=SessionStatus.ACTIVE, db_index=True
    )
    tariff = models.ForeignKey(
        "pricing.Tariff", null=True, blank=True, on_delete=models.PROTECT,
        related_name="sessions",
    )
    customer_rate = models.ForeignKey(
        "pricing.CustomerRate", null=True, blank=True, on_delete=models.PROTECT,
        related_name="sessions",
    )
    tariff_name = models.CharField(max_length=80)
    hourly_rate = models.PositiveIntegerField()
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    elapsed_seconds = models.PositiveIntegerField(null=True, blank=True)
    cost = models.PositiveIntegerField(null=True, blank=True)
    discount_percent = models.PositiveSmallIntegerField(default=0)
    discount_amount = models.PositiveIntegerField(default=0)
    discount_source = models.CharField(max_length=80, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    end_reason = models.CharField(max_length=120, blank=True)
    is_replica = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=SessionStatus.values),
                name="gaming_sessions_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status=SessionStatus.ACTIVE, ended_at__isnull=True)
                    | (~models.Q(status=SessionStatus.ACTIVE) & models.Q(ended_at__isnull=False))
                ),
                name="gaming_sessions_end_matches_status",
            ),
            models.UniqueConstraint(
                fields=["device"],
                condition=models.Q(status=SessionStatus.ACTIVE),
                name="gaming_sessions_one_active_per_device",
            ),
            models.CheckConstraint(
                condition=~(
                    models.Q(tariff__isnull=False) & models.Q(customer_rate__isnull=False)
                ),
                name="gaming_sessions_single_rate_source",
            ),
        ]
        indexes = [
            models.Index(fields=["edge_id", "status", "-started_at"]),
            models.Index(fields=["customer", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.customer_id} @ {self.device_id} [{self.status}]"
