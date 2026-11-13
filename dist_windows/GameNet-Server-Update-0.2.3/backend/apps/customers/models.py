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
    username = models.CharField(max_length=60, blank=True, default="", db_index=True)
    password_hash = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=24, blank=True, db_index=True)
    group = models.ForeignKey(
        "customer_groups.CustomerGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customers",
    )
    credit_limit = models.PositiveIntegerField(default=settings.DEFAULT_CREDIT_LIMIT)
    debt_balance = models.PositiveIntegerField(default=0)
    max_debt_limit = models.PositiveIntegerField(default=40_000)
    active_coupons = models.PositiveSmallIntegerField(
        default=0,
        help_text="تعداد کوپن‌های فعال ۵۰٪ رهرو (هر کوپن معادل ۱ ساعت بازی با نرخ ۲۰,۰۰۰ تومان)",
    )
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)
    is_replica = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
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

    def set_password(self, raw_password: str) -> None:
        from django.contrib.auth.hashers import make_password
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        from django.contrib.auth.hashers import check_password
        if not self.password_hash:
            return False
        return check_password(raw_password, self.password_hash)

    def __str__(self) -> str:
        return self.full_name

    @property
    def has_debt(self) -> bool:
        return self.debt_balance > 0
