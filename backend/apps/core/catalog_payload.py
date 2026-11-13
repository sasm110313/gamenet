"""Shared catalog JSON serializer for guided session start and wallet recharge UIs."""

from __future__ import annotations

import json


def build_catalog_json(
    *,
    customers,
    tariffs,
    devices,
    default_hourly_rate: int,
    operator_label: str = "",
) -> str:
    """Serialize customers (with balance & personal rates), tariffs, and devices into JSON."""
    customer_items = []
    for c in customers:
        wallet = getattr(c, "wallet", None)
        balance = int(wallet.balance) if wallet is not None else 0
        credit_limit = int(getattr(c, "credit_limit", 0) or 0)
        debt_balance = int(getattr(c, "debt_balance", 0) or 0)
        max_debt_limit = int(getattr(c, "max_debt_limit", 40000) or 40000)

        personal_rates = []
        default_rate = None
        for r in c.rates.all():
            if not r.is_active:
                continue
            item = {
                "id": str(r.id),
                "name": r.name,
                "hourly_rate": int(r.hourly_rate),
                "is_default": bool(r.is_default),
            }
            personal_rates.append(item)
            if r.is_default and default_rate is None:
                default_rate = item

        group = getattr(c, "group", None)
        group_tariff = group.tariff if (group and group.is_active and group.tariff and group.tariff.is_active) else None

        if default_rate is not None:
            eff_rate = default_rate["hourly_rate"]
            eff_name = default_rate["name"]
        elif group_tariff is not None:
            eff_rate = int(group_tariff.hourly_rate)
            eff_name = f"تعرفه گروه ({group_tariff.name})"
        else:
            eff_rate = int(default_hourly_rate)
            eff_name = "تعرفه پیش‌فرض سالن"

        customer_items.append(
            {
                "id": str(c.id),
                "name": c.full_name,
                "full_name": c.full_name,
                "username": c.username or "",
                "phone": c.phone or "",
                "balance": balance,
                "debt_balance": debt_balance,
                "max_debt_limit": max_debt_limit,
                "credit_limit": credit_limit,
                "available": balance + credit_limit,
                "default_hourly_rate": eff_rate,
                "default_rate_name": eff_name,
                "effective_rate": eff_rate,
                "effective_rate_source": eff_name,
                "has_personal_or_group_rate": bool(default_rate or group_tariff),
                "rates": personal_rates,
            }
        )

    tariff_items = [
        {
            "id": str(t.id),
            "name": t.name,
            "hourly_rate": int(t.hourly_rate),
        }
        for t in tariffs
    ]

    device_items = [
        {
            "id": str(d.id),
            "name": d.name,
            "connection_status": d.connection_status,
            "power_status": d.power_status,
            "kiosk_status": d.kiosk_status,
            "occupancy_status": d.occupancy_status,
            "health_status": d.health_status,
            "default_tariff_id": str((d.metadata or {}).get("default_tariff_id") or ""),
            "busy": bool(getattr(d, "active_session", None) or d.occupancy_status == "BUSY"),
        }
        for d in devices
    ]

    return json.dumps(
        {
            "default_hourly_rate": int(default_hourly_rate),
            "operator_label": operator_label or "",
            "customers": customer_items,
            "tariffs": tariff_items,
            "devices": device_items,
        },
        ensure_ascii=False,
    )
