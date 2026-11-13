from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from apps.core.announcements import (
    get_announcements,
    get_active_announcements,
    get_announcements_hash,
    add_announcement,
    update_announcement,
    delete_announcement,
    toggle_announcement,
    save_announcements,
    DEFAULT_ANNOUNCEMENTS,
)


@login_required
@require_http_methods(["GET", "POST"])
def announcements_list(request):
    """View and manage salon announcements and user notices."""
    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "add":
            title = request.POST.get("title", "").strip()
            content = request.POST.get("content", "").strip()
            msg_type = request.POST.get("type", "info").strip()
            priority = request.POST.get("priority", "1").strip()
            is_active = request.POST.get("is_active") == "on"

            if not title or not content:
                messages.error(request, "عنوان و متن پیام الزامی است.")
            else:
                author = f"مدیریت سالن ({request.user.get_full_name() or request.user.username})"
                add_announcement(
                    title=title,
                    content=content,
                    msg_type=msg_type,
                    priority=int(priority) if priority.isdigit() else 1,
                    is_active=is_active,
                    author=author,
                )
                messages.success(request, f"اطلاعیه «{title}» با موفقیت ثبت شد و به سیستم‌ها ارسال گردید.")

        elif action == "edit":
            ann_id = request.POST.get("ann_id", "").strip()
            title = request.POST.get("title", "").strip()
            content = request.POST.get("content", "").strip()
            msg_type = request.POST.get("type", "info").strip()
            priority = request.POST.get("priority", "1").strip()
            is_active = request.POST.get("is_active") == "on"

            if not ann_id or not title or not content:
                messages.error(request, "شناسه، عنوان و متن پیام الزامی است.")
            else:
                res = update_announcement(
                    ann_id=ann_id,
                    title=title,
                    content=content,
                    msg_type=msg_type,
                    priority=int(priority) if priority.isdigit() else 1,
                    is_active=is_active,
                )
                if res:
                    messages.success(request, f"تغییرات اطلاعیه «{title}» با موفقیت ذخیره شد.")
                else:
                    messages.error(request, "اطلاعیه مورد نظر یافت نشد.")

        elif action == "delete":
            ann_id = request.POST.get("ann_id", "").strip()
            if delete_announcement(ann_id):
                messages.success(request, "اطلاعیه حذف شد.")
            else:
                messages.error(request, "اطلاعیه یافت نشد.")

        elif action == "toggle":
            ann_id = request.POST.get("ann_id", "").strip()
            new_state = toggle_announcement(ann_id)
            messages.success(request, f"وضعیت اطلاعیه به {'فعال' if new_state else 'غیرفعال'} تغییر یافت.")

        elif action == "reset":
            save_announcements(DEFAULT_ANNOUNCEMENTS)
            messages.success(request, "اطلاعیه‌ها به پیام پیش‌فرض خوش‌آمدگویی بازی سرای رهرو بازنشانی شدند.")

        next_url = request.POST.get("next") or request.path
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = request.path
        return redirect(next_url)

    # GET
    announcements = get_announcements()
    ctx = {
        "announcements": announcements,
        "announcements_total": len(announcements),
        "announcements_active": sum(1 for a in announcements if a.get("is_active", True)),
    }
    return render(request, "announcements/announcements_list.html", ctx)


def api_announcements(request):
    """API returning active announcements list for kiosk clients."""
    active_only = request.GET.get("all") != "1"
    items = get_active_announcements() if active_only else get_announcements()
    return JsonResponse({
        "ok": True,
        "announcements": items,
        "hash": get_announcements_hash(),
    })
