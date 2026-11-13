from __future__ import annotations

from django.db import models


class Wallet(models.Model):
    """Prepaid balance. A negative balance is allowed down to -credit_limit.

    The wallet row is always mutated together with an append-only ledger entry in
    the same transaction, under `SELECT ... FOR UPDATE` plus a customer advisory
    lock.
    """

    customer = models.OneToOneField(
        "customers.Customer",
        primary_key=True,
        on_delete=models.PROTECT,
        related_name="wallet",
    )
    balance = models.IntegerField(default=0)
    is_replica = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["customer__full_name"]

    def __str__(self) -> str:
        return f"{self.customer_id}: {self.balance:,}"
