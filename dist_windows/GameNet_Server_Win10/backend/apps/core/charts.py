"""Shared revenue chart aggregation helpers for Edge and Cloud dashboards."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.sessions.models import GamingSession, SessionStatus

WEEKDAY_NAMES_FA = [
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنج‌شنبه",
    "جمعه",
    "شنبه",
    "یکشنبه",
]


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    y, m0 = divmod(total, 12)
    return y, m0 + 1


def _finalize_heights(items: list[dict]) -> list[dict]:
    max_val = max((item["total"] for item in items), default=0)
    max_val = max(1, max_val)
    for item in items:
        item["height_pct"] = (
            max(8, int((item["total"] / max_val) * 100)) if item["total"] > 0 else 5
        )
    return items


def _sum_window(start_d: date, end_d: date, tz) -> tuple[int, int]:
    dt_start = timezone.make_aware(datetime.combine(start_d, time.min), tz)
    dt_end = timezone.make_aware(datetime.combine(end_d, time.max), tz)
    day_session = (
        GamingSession.objects.filter(
            ended_at__gte=dt_start,
            ended_at__lte=dt_end,
            status=SessionStatus.COMPLETED,
        ).aggregate(total=Sum("cost"))["total"]
        or 0
    )
    day_deposit = (
        LedgerEntry.objects.filter(
            created_at__gte=dt_start,
            created_at__lte=dt_end,
            entry_type=LedgerEntryType.DEPOSIT,
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return int(day_session), int(day_deposit)


def build_revenue_charts(today: date) -> dict[str, list[dict]]:
    tz = timezone.get_current_timezone()

    daily: list[dict] = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        day_session, day_deposit = _sum_window(d, d, tz)
        day_name = WEEKDAY_NAMES_FA[d.weekday()]
        daily.append(
            {
                "label": f"{d.month}/{d.day}",
                "day_name": day_name,
                "tooltip_title": f"{day_name} ({d.month}/{d.day})",
                "session": day_session,
                "deposit": day_deposit,
                "total": day_session,
                "height_pct": 5,
            }
        )

    weekly: list[dict] = []
    for w in range(5, -1, -1):
        w_end = today - timedelta(days=w * 7)
        w_start = w_end - timedelta(days=6)
        w_session, w_deposit = _sum_window(w_start, w_end, tz)
        weekly.append(
            {
                "label": f"{w_start.month}/{w_start.day}",
                "day_name": f"{w_start.month}/{w_start.day}–{w_end.month}/{w_end.day}",
                "tooltip_title": f"هفته {w_start.month}/{w_start.day} تا {w_end.month}/{w_end.day}",
                "session": w_session,
                "deposit": w_deposit,
                "total": w_session,
                "height_pct": 5,
            }
        )

    monthly: list[dict] = []
    for m_off in range(-5, 1):
        y, m = _shift_month(today.year, today.month, m_off)
        m_start = date(y, m, 1)
        last_day = calendar.monthrange(y, m)[1]
        m_end = min(today, date(y, m, last_day)) if (y == today.year and m == today.month) else date(y, m, last_day)
        m_session, m_deposit = _sum_window(m_start, m_end, tz)
        monthly.append(
            {
                "label": f"{y}/{m:02d}",
                "day_name": f"{y}/{m:02d}",
                "tooltip_title": f"ماه {y}/{m:02d}",
                "session": m_session,
                "deposit": m_deposit,
                "total": m_session,
                "height_pct": 5,
            }
        )

    return {
        "daily": _finalize_heights(daily),
        "weekly": _finalize_heights(weekly),
        "monthly": _finalize_heights(monthly),
    }
