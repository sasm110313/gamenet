from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class SessionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class BillingMode(models.TextChoices):
    CREDIT = "CREDIT", "Credit-based"
    TIMED = "TIMED", "Fixed time"


class DisconnectPolicy(models.TextChoices):
    CONTINUE = "CONTINUE", "Continue timer on disconnect"
    PAUSE = "PAUSE", "Pause timer on disconnect"
    AUTO_STOP = "AUTO_STOP", "Auto-stop on disconnect"


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
    billing_mode = models.CharField(
        max_length=16,
        choices=BillingMode.choices,
        default=BillingMode.CREDIT,
        db_index=True,
    )
    planned_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    estimated_cost = models.PositiveIntegerField(default=0)
    disconnect_policy = models.CharField(
        max_length=16,
        choices=DisconnectPolicy.choices,
        default=DisconnectPolicy.PAUSE,
        db_index=True,
    )
    connection_lost_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_seconds = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    elapsed_seconds = models.PositiveIntegerField(null=True, blank=True)
    cost = models.PositiveIntegerField(null=True, blank=True)
    discount_percent = models.PositiveSmallIntegerField(default=0)
    discount_amount = models.PositiveIntegerField(default=0)
    discount_source = models.CharField(max_length=80, blank=True)
    coupon_hours = models.PositiveSmallIntegerField(
        default=0, help_text="تعداد ساعات مشمول تخفیف کوپن ۵۰٪"
    )
    coupon_hourly_rate = models.PositiveIntegerField(
        default=20000, help_text="نرخ هر ساعت تخفیف کوپن"
    )
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
                condition=models.Q(billing_mode__in=BillingMode.values),
                name="gaming_sessions_billing_mode_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(disconnect_policy__in=DisconnectPolicy.values),
                name="gaming_sessions_disconnect_policy_valid",
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

    def current_paused_seconds(self, at=None) -> int:
        total = int(self.paused_seconds or 0)
        if self.paused_at and self.status == SessionStatus.ACTIVE:
            now = at or timezone.now()
            total += max(0, int((now - self.paused_at).total_seconds()))
        return total

    def billable_elapsed_seconds(self, at=None) -> int:
        if self.elapsed_seconds is not None and self.status != SessionStatus.ACTIVE:
            return int(self.elapsed_seconds)
        now = at or timezone.now()
        raw = max(0, int((now - self.started_at).total_seconds()))
        return max(0, raw - self.current_paused_seconds(now))

    def calculate_cost(self, elapsed_seconds: int) -> tuple[int, int]:
        """محاسبه هزینه نهایی و تخفیف بر اساس مدت زمان بازی، کوپن‌های اعمال‌شده و تعرفه.
        خروجی: (cost, discount_amount)
        """
        if elapsed_seconds <= 0:
            return 0, 0

        from apps.core.money import session_cost

        normal_rate = self.hourly_rate or 40000
        coupon_hrs = getattr(self, "coupon_hours", 0) or 0
        coupon_rate = getattr(self, "coupon_hourly_rate", 20000) or 20000

        # اگر کوپن ۵۰٪ برای ساعات مشخصی فعال باشد
        if coupon_hrs > 0 and coupon_rate < normal_rate:
            coupon_sec = coupon_hrs * 3600
            if elapsed_seconds <= coupon_sec:
                cost = session_cost(coupon_rate, elapsed_seconds)
                discount_amount = session_cost(normal_rate - coupon_rate, elapsed_seconds)
            else:
                cost_coupon_part = session_cost(coupon_rate, coupon_sec)
                cost_normal_part = session_cost(normal_rate, elapsed_seconds - coupon_sec)
                cost = cost_coupon_part + cost_normal_part
                discount_amount = session_cost(normal_rate - coupon_rate, coupon_sec)
            return cost, discount_amount

        # تخفیف درصدی عادی
        base_cost = session_cost(normal_rate, elapsed_seconds)
        if self.discount_percent > 0:
            discount_amount = (base_cost * self.discount_percent + 50) // 100
            cost = max(0, base_cost - discount_amount)
            return cost, discount_amount

        return base_cost, 0
