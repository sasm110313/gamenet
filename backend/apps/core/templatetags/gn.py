from __future__ import annotations

import uuid

from django import template
from django.utils import timezone

register = template.Library()

STATUS_FA = {
    "OFFLINE": "آفلاین",
    "ONLINE": "آنلاین",
    "LOCKED": "قفل",
    "IDLE": "بی‌کار",
    "STARTING": "در حال شروع",
    "ACTIVE": "در حال بازی",
    "STOPPING": "در حال پایان",
    "ERROR": "خطا",
    "MAINTENANCE": "تعمیرات",
    "PENDING": "در انتظار",
    "SYNCING": "در حال ارسال",
    "SYNCED": "همگام",
    "FAILED": "ناموفق",
    "APPLIED": "اعمال شد",
    "REJECTED": "رد شد",
    "SENT": "ارسال شد",
    "ACKNOWLEDGED": "تأیید شد",
    "EXPIRED": "منقضی",
    "RECEIVED": "دریافت شد",
    "EXECUTING": "در حال اجرا",
    "SUCCEEDED": "موفق",
    "REGISTERED": "ثبت‌شده",
    "REVOKED": "لغو شده",
}

TONES = {
    "OFFLINE": "st-offline",
    "ONLINE": "st-online",
    "LOCKED": "st-locked",
    "IDLE": "st-idle",
    "STARTING": "st-pending",
    "ACTIVE": "st-online",
    "STOPPING": "st-pending",
    "ERROR": "st-error",
    "MAINTENANCE": "st-maintenance",
    "PENDING": "st-pending",
    "SYNCING": "st-syncing",
    "SYNCED": "st-synced",
    "FAILED": "st-failed",
    "APPLIED": "st-applied",
    "REJECTED": "st-rejected",
    "SENT": "st-sent",
    "ACKNOWLEDGED": "st-acknowledged",
    "EXPIRED": "st-expired",
    "RECEIVED": "st-pending",
    "EXECUTING": "st-executing",
    "SUCCEEDED": "st-succeeded",
    "REGISTERED": "st-registered",
    "REVOKED": "st-revoked",
}

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@register.simple_tag
def uuid4():
    return str(uuid.uuid4())


@register.filter
def status_fa(value):
    return STATUS_FA.get(str(value), str(value))


@register.filter
def status_tone(value):
    return TONES.get(str(value), "st-offline")


@register.filter
def fa_digits(value):
    return str(value).translate(FA_DIGITS)


@register.filter
def reltime(value):
    if not value:
        return "—"
    delta = (timezone.now() - value).total_seconds()
    future = delta < 0
    delta = abs(delta)
    if delta < 60:
        text = f"{int(delta)}s"
    elif delta < 3600:
        text = f"{int(delta // 60)}m"
    elif delta < 86400:
        text = f"{int(delta // 3600)}h"
    else:
        text = f"{int(delta // 86400)}d"
    return f"{text} بعد" if future else f"{text} پیش"


@register.filter
def shortid(value):
    return str(value)[:8]


@register.filter
def station_num(name):
    """Converts 'PC-01' -> '1', 'PC-10' -> '10', '1' -> '1'."""
    if not name:
        return ""
    s = str(name).strip()
    if s.upper().startswith("PC-"):
        part = s[3:]
        try:
            return str(int(part))
        except ValueError:
            return part
    return s


@register.filter
def toman(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


@register.filter
def duration_hms(seconds):
    if seconds is None:
        return "00:00:00"
    try:
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"
    except (ValueError, TypeError):
        return "00:00:00"


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key, 0)
    except AttributeError:
        return 0
