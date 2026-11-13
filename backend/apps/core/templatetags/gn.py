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
def sub(value, arg):
    try:
        return int(value or 0) - int(arg or 0)
    except (ValueError, TypeError):
        return 0


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


CONN_FA = {
    "ONLINE": "آنلاین",
    "OFFLINE": "آفلاین",
}

CONN_TONE = {
    "ONLINE": "st-online",
    "OFFLINE": "st-offline",
}

POWER_FA = {
    "ON": "روشن",
    "OFF": "خاموش",
    "UNKNOWN": "نامشخص",
}

POWER_TONE = {
    "ON": "st-online",
    "OFF": "st-offline",
    "UNKNOWN": "st-pending",
}

KIOSK_FA = {
    "LOCKED": "قفل کیوسک",
    "UNLOCKED": "باز",
    "DISABLED": "خروج از کیوسک",
}

KIOSK_TONE = {
    "LOCKED": "st-locked",
    "UNLOCKED": "st-online",
    "DISABLED": "st-pending",
}

OCC_FA = {
    "FREE": "آزاد",
    "BUSY": "مشغول",
    "MAINTENANCE": "تعمیرات",
}

OCC_TONE = {
    "FREE": "st-idle",
    "BUSY": "st-active",
    "MAINTENANCE": "st-maintenance",
}

HEALTH_FA = {
    "HEALTHY": "سالم",
    "ERROR": "خطا",
}

HEALTH_TONE = {
    "HEALTHY": "st-online",
    "ERROR": "st-error",
}

BILLING_MODE_FA = {
    "CREDIT": "اعتبارمحور",
    "TIMED": "زمانی",
}

DISCONNECT_POLICY_FA = {
    "PAUSE": "توقف شمارنده در قطعی",
    "AUTO_STOP": "توقف خودکار پس از ۶۰ ثانیه قطعی",
    "CONTINUE": "ادامه شمارنده با هشدار",
}


@register.filter
def conn_fa(value):
    return CONN_FA.get(str(value), str(value))


@register.filter
def conn_tone(value):
    return CONN_TONE.get(str(value), "st-offline")


@register.filter
def power_fa(value):
    return POWER_FA.get(str(value), str(value))


@register.filter
def power_tone(value):
    return POWER_TONE.get(str(value), "st-pending")


@register.filter
def kiosk_fa(value):
    return KIOSK_FA.get(str(value), str(value))


@register.filter
def kiosk_tone(value):
    return KIOSK_TONE.get(str(value), "st-locked")


@register.filter
def occ_fa(value):
    return OCC_FA.get(str(value), str(value))


@register.filter
def occ_tone(value):
    return OCC_TONE.get(str(value), "st-idle")


@register.filter
def health_fa(value):
    return HEALTH_FA.get(str(value), str(value))


@register.filter
def health_tone(value):
    return HEALTH_TONE.get(str(value), "st-error")


@register.filter
def billing_mode_fa(value):
    return BILLING_MODE_FA.get(str(value), str(value))


@register.filter
def disconnect_policy_fa(value):
    return DISCONNECT_POLICY_FA.get(str(value), str(value))


@register.filter
def os_fa(value):
    if not value:
        return "ویندوز"
    v = str(value).lower()
    arch = " (32-bit)" if ("ia32" in v or "x86" in v) else (" (64-bit)" if ("x64" in v or "amd64" in v) else "")
    if "6.1" in v or "windows 7" in v:
        return f"ویندوز ۷{arch}"
    if "10.0" in v or "windows 10" in v:
        return f"ویندوز ۱۰{arch}"
    if "6.3" in v or "windows 8.1" in v:
        return f"ویندوز ۸.۱{arch}"
    if "windows" in v:
        return f"ویندوز{arch}"
    if "linux" in v:
        return "لینوکس"
    return str(value)

