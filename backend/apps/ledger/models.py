from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


def generate_tracking_code(at=None) -> str:
    """Return a unique human-readable tracking code for an immutable ledger entry."""
    dt = timezone.localtime(at or timezone.now())
    return f"TR-{dt.strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"


class LedgerEntryType(models.TextChoices):
    DEPOSIT = "DEPOSIT", "Deposit"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"
    SESSION_CHARGE = "SESSION_CHARGE", "Session charge"
    REVERSAL = "REVERSAL", "Reversal"
    DEBT_PAYMENT = "DEBT_PAYMENT", "Debt payment"


class LedgerEntry(models.Model):
    """Append-only money history. Insert-only by construction.

    `amount` is signed: positive credits the wallet, negative debits it.
    `balance_after` is the authoritative balance at that point in the stream.
    Corrections are REVERSAL rows that reference the original entry; nothing is
    ever updated or deleted.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge_id = models.UUIDField(db_index=True)
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    session = models.ForeignKey(
        "gaming_sessions.GamingSession",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(max_length=24, choices=LedgerEntryType.choices, db_index=True)
    amount = models.IntegerField()
    balance_after = models.IntegerField()
    reverses = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversal",
    )
    note = models.CharField(max_length=255, blank=True)
    tracking_code = models.CharField(
        max_length=32, unique=True, default=generate_tracking_code
    )
    operator_label = models.CharField(max_length=120, blank=True)
    is_debt = models.BooleanField(default=False)
    source_command_id = models.UUIDField(null=True, blank=True, unique=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_replica = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0), name="ledger_amount_nonzero"
            ),
            models.CheckConstraint(
                condition=models.Q(entry_type__in=LedgerEntryType.values),
                name="ledger_entry_type_valid",
            ),
            models.UniqueConstraint(
                fields=["session", "entry_type"],
                condition=models.Q(session__isnull=False),
                name="ledger_one_entry_per_session_type",
            ),
        ]
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["edge_id", "created_at"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.amount > 0 else ""
        return f"{self.entry_type} {sign}{self.amount:,} -> {self.balance_after:,}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("LedgerEntry is append-only")
        if not self.tracking_code:
            self.tracking_code = generate_tracking_code(self.created_at)
        if not self.operator_label and self.created_by_id:
            user = self._state.fields_cache.get("created_by")
            if user is not None:
                self.operator_label = user.label
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # pragma: no cover - guard
        raise ValueError("LedgerEntry is append-only")
