from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from typing import Any
from django.conf import settings
from django.utils import timezone

DEFAULT_ANNOUNCEMENTS = [
    {
        "id": "ann_welcome",
        "title": "به بازی سرای رهرو خوش آمدید",
        "content": "ساعات خوش و پرهیجانی را برای شما عزیزان آرزومندیم. لطفاً در حفظ نظافت سالن، رعایت آرامش و نگهداری صحیح از تجهیزات و دسته‌ها کوشا باشید. در صورت نیاز به راهنمایی، شارژ حساب یا سفارش بوفه به مسئول سالن مراجعه فرمایید.",
        "type": "info",
        "priority": 1,
        "is_active": True,
        "created_at": "2026-11-10T12:00:00+03:30",
        "author": "مدیریت بازی سرای رهرو",
    }
]


def _announcements_path() -> str:
    env_dir = os.environ.get("GAMENET_DATA_DIR")
    if env_dir:
        try:
            os.makedirs(env_dir, exist_ok=True)
            return os.path.join(env_dir, "announcements.json")
        except OSError:
            pass

    base_dir = getattr(settings, "BASE_DIR", os.getcwd())
    candidates = [
        os.path.join(base_dir, ".runtime"),
        os.path.join(base_dir, "data"),
        "/opt/gamenet/backend/.runtime",
        os.path.join(tempfile.gettempdir(), "gamenet_data"),
    ]

    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            test_file = os.path.join(candidate, ".ann_test")
            with open(test_file, "w") as f:
                f.write("1")
            os.remove(test_file)
            return os.path.join(candidate, "announcements.json")
        except OSError:
            continue

    return os.path.join(tempfile.gettempdir(), "announcements.json")


def _announcements_hash(items: list[dict[str, Any]]) -> str:
    raw = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def get_announcements() -> list[dict[str, Any]]:
    path = _announcements_path()
    if not os.path.exists(path):
        save_announcements(DEFAULT_ANNOUNCEMENTS)
        return list(DEFAULT_ANNOUNCEMENTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return list(DEFAULT_ANNOUNCEMENTS)


def get_active_announcements() -> list[dict[str, Any]]:
    all_items = get_announcements()
    active = [item for item in all_items if item.get("is_active", True)]
    # Sort by priority descending, then created_at descending
    active.sort(key=lambda x: (int(x.get("priority", 1)), str(x.get("created_at", ""))), reverse=True)
    return active


def get_announcements_hash() -> str:
    active = get_active_announcements()
    return _announcements_hash(active)


def save_announcements(items: list[dict[str, Any]]) -> None:
    path = _announcements_path()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

    # Broadcast to connected kiosks over WebSocket
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                "gamenet_all_devices",
                {"type": "device.announcements_updated"},
            )
    except Exception:
        pass


def add_announcement(
    title: str,
    content: str,
    msg_type: str = "info",
    priority: int = 1,
    is_active: bool = True,
    author: str = "مدیریت بازی سرای رهرو",
) -> dict[str, Any]:
    items = get_announcements()
    ann_id = "ann_" + uuid.uuid4().hex[:8]
    item = {
        "id": ann_id,
        "title": title.strip(),
        "content": content.strip(),
        "type": msg_type.strip() if msg_type in {"info", "warning", "success", "danger"} else "info",
        "priority": int(priority) if str(priority).isdigit() else 1,
        "is_active": bool(is_active),
        "created_at": timezone.now().isoformat(),
        "author": author.strip() or "مدیریت بازی سرای رهرو",
    }
    items.insert(0, item)
    save_announcements(items)
    return item


def update_announcement(
    ann_id: str,
    title: str,
    content: str,
    msg_type: str = "info",
    priority: int = 1,
    is_active: bool = True,
) -> dict[str, Any] | None:
    items = get_announcements()
    for i, it in enumerate(items):
        if it.get("id") == ann_id:
            items[i] = {
                "id": ann_id,
                "title": title.strip(),
                "content": content.strip(),
                "type": msg_type.strip() if msg_type in {"info", "warning", "success", "danger"} else "info",
                "priority": int(priority) if str(priority).isdigit() else 1,
                "is_active": bool(is_active),
                "created_at": it.get("created_at") or timezone.now().isoformat(),
                "author": it.get("author") or "مدیریت بازی سرای رهرو",
            }
            save_announcements(items)
            return items[i]
    return None


def delete_announcement(ann_id: str) -> bool:
    items = get_announcements()
    initial_len = len(items)
    items = [it for it in items if it.get("id") != ann_id]
    if len(items) != initial_len:
        save_announcements(items)
        return True
    return False


def toggle_announcement(ann_id: str) -> bool:
    items = get_announcements()
    for it in items:
        if it.get("id") == ann_id:
            it["is_active"] = not it.get("is_active", True)
            save_announcements(items)
            return it["is_active"]
    return False
