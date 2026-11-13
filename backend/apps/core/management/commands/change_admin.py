from __future__ import annotations

import getpass
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Change the salon administrator username, display name, and password."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="New admin username")
        parser.add_argument("--password", help="New admin password")
        parser.add_argument("--display-name", help="New display name / label")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).order_by("date_joined").first()
        if user is None:
            user = User.objects.filter(is_staff=True).order_by("date_joined").first()

        new_username = options.get("username")
        new_password = options.get("password")
        new_display_name = options.get("display_name")

        # Interactive prompts if arguments not supplied
        if not new_username and not new_password and not new_display_name:
            curr_info = f" ({user.username})" if user else ""
            self.stdout.write("=========================================================")
            self.stdout.write(f" تغییر اطلاعات مدیر بازی سرای رهرو{curr_info}")
            self.stdout.write("=========================================================")

            prompt_user = input(f"نام کاربری جدید [{user.username if user else 'admin'}]: ").strip()
            if prompt_user:
                new_username = prompt_user

            prompt_name = input(f"نام نمایشی مدیر [{user.display_name if (user and user.display_name) else 'مدیر سالن'}]: ").strip()
            if prompt_name:
                new_display_name = prompt_name

            prompt_pass = getpass.getpass("رمز عبور جدید (برای عدم تغییر Enter بزنید): ").strip()
            if prompt_pass:
                confirm_pass = getpass.getpass("تکرار رمز عبور جدید: ").strip()
                if prompt_pass != confirm_pass:
                    self.stderr.write(self.style.ERROR("[خطا] تکرار رمز عبور یکسان نیست! عملیات لغو شد."))
                    return
                new_password = prompt_pass

        if user is None:
            # Create fresh superuser
            uname = new_username or "admin"
            pword = new_password or "admin123"
            dname = new_display_name or "مدیر سالن"
            user = User.objects.create_superuser(
                username=uname,
                password=pword,
                email="admin@gamenet.local",
                display_name=dname,
            )
            self.stdout.write(self.style.SUCCESS(f"کاربر مدیر جدید با موفقیت ایجاد شد: {uname}"))
            return

        # Update existing superuser
        changed_fields = []
        if new_username and new_username != user.username:
            # Check collision
            if User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                self.stderr.write(self.style.ERROR(f"[خطا] نام کاربری '{new_username}' قبلاً استفاده شده است."))
                return
            user.username = new_username
            changed_fields.append(f"نام کاربری: {new_username}")

        if new_display_name is not None and new_display_name != user.display_name:
            user.display_name = new_display_name
            changed_fields.append(f"نام نمایشی: {new_display_name}")

        if new_password:
            user.set_password(new_password)
            changed_fields.append("رمز عبور جدید")

        if changed_fields:
            user.save()
            self.stdout.write(self.style.SUCCESS(f"اطلاعات کاربر مدیر با موفقیت به‌روزرسانی شد: {', '.join(changed_fields)}"))
        else:
            self.stdout.write("هیچ تغییری اعمال نشد.")
