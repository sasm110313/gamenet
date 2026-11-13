from __future__ import annotations

import re
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


@login_required
def account_settings(request):
    """View to change admin username, display name, and password."""
    user = request.user
    User = get_user_model()
    is_edge = getattr(settings, "GAMENET_ROLE", "edge") == "edge"

    if request.method == "POST":
        new_username = request.POST.get("username", "").strip()
        new_display_name = request.POST.get("display_name", "").strip()
        current_password = request.POST.get("current_password", "").strip()
        new_password = request.POST.get("new_password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        errors = []

        # 1. Validate Username
        if not new_username:
            errors.append("نام کاربری نمی‌تواند خالی باشد.")
        elif len(new_username) < 3:
            errors.append("نام کاربری باید حداقل ۳ کاراکتر باشد.")
        elif not re.match(r"^[\w.@+-]+$", new_username):
            errors.append("نام کاربری تنها می‌تواند شامل حروف انگلیسی، اعداد و کاراکترهای @/./+/-/_ باشد.")
        elif User.objects.filter(username__iexact=new_username).exclude(pk=user.pk).exists():
            errors.append(f"نام کاربری '{new_username}' قبلاً ثبت شده است.")

        # 2. Validate Password Change (if requested)
        password_changed = False
        if new_password or confirm_password or current_password:
            if not current_password:
                errors.append("برای تغییر رمز عبور، وارد کردن رمز فعلی الزامی است.")
            elif not user.check_password(current_password):
                errors.append("رمز عبور فعلی نادرست است.")

            if not new_password:
                errors.append("لطفاً رمز عبور جدید را وارد کنید.")
            elif len(new_password) < 4:
                errors.append("رمز عبور جدید باید حداقل ۴ کاراکتر باشد.")
            elif new_password != confirm_password:
                errors.append("تکرار رمز عبور جدید مطابقت ندارد.")
            else:
                password_changed = True

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            user.username = new_username
            user.display_name = new_display_name
            if password_changed:
                user.set_password(new_password)

            user.save()

            if password_changed:
                # Keep user logged in with new password hash
                update_session_auth_hash(request, user)
                messages.success(request, "نام کاربری و رمز عبور جدید با موفقیت ذخیره شدند.")
            else:
                messages.success(request, "مشخصات حساب کاربری با موفقیت به‌روزرسانی شد.")

            return redirect(request.path)

    context = {
        "admin_user": user,
        "is_edge": is_edge,
    }
    return render(request, "accounts/account_settings.html", context)
