from django.core.management.base import BaseCommand
import uuid
from apps.pricing.models import Tariff, CustomerRate
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.sessions.models import GamingSession
from apps.synchronization.models import EdgeNode, EdgeIdentity, ConfigSnapshot, AppliedConfig
import hashlib
import json


class Command(BaseCommand):
    help = "تنظیم و تثبیت دقیق تعرفه‌ها و گروه‌های سه‌گانه گیم‌نت: آزاد (۶۰ ت)، لیگ رهرو (۴۰ ت)، کادر (۲۰ ت) و حذف هرگونه تعرفه یا گروه اضافی"

    def handle(self, *args, **options):
        edge_id = None
        ident = EdgeIdentity.objects.first()
        if ident and ident.edge_id:
            edge_id = ident.edge_id
        if not edge_id:
            edge = EdgeNode.objects.filter(revoked_at__isnull=True).order_by("-last_heartbeat_at").first()
            if edge:
                edge_id = edge.id
        if not edge_id:
            edge_id = uuid.UUID("01a18e45-00ea-7f5b-8631-0d6406670e55")

        self.stdout.write("در حال تثبیت تعرفه‌ها و گروه‌های اختصاصی سه‌گانه...")

        # ۱. تعرفه و گروه آزاد (۶۰ هزار تومان - پیش‌فرض سالن)
        free_tariff, _ = Tariff.objects.get_or_create(
            name="آزاد",
            defaults={"hourly_rate": 60000, "is_active": True, "edge_id": edge_id, "is_replica": False}
        )
        if free_tariff.hourly_rate != 60000 or not free_tariff.is_active:
            free_tariff.hourly_rate = 60000
            free_tariff.is_active = True
            free_tariff.save(update_fields=["hourly_rate", "is_active"])
        self.stdout.write(self.style.SUCCESS(f"✓ تعرفه آزاد (پیش‌فرض): {free_tariff.hourly_rate:,} تومان/ساعت"))

        free_group, _ = CustomerGroup.objects.get_or_create(
            name="آزاد",
            defaults={"tariff": free_tariff, "is_active": True, "edge_id": edge_id, "is_replica": False}
        )
        if free_group.tariff_id != free_tariff.id or not free_group.is_active:
            free_group.tariff = free_tariff
            free_group.is_active = True
            free_group.save(update_fields=["tariff", "is_active"])
        self.stdout.write(self.style.SUCCESS(f"✓ گروه آزاد: متصل به {free_tariff.name} ({free_tariff.hourly_rate:,} ت)"))

        # ۲. تعرفه و گروه لیگ رهرو (۴۰ هزار تومان)
        rahro_tariff, _ = Tariff.objects.get_or_create(
            name="لیگ رهرو",
            defaults={"hourly_rate": 40000, "is_active": True, "edge_id": edge_id, "is_replica": False}
        )
        if rahro_tariff.hourly_rate != 40000 or not rahro_tariff.is_active:
            rahro_tariff.hourly_rate = 40000
            rahro_tariff.is_active = True
            rahro_tariff.save(update_fields=["hourly_rate", "is_active"])
        self.stdout.write(self.style.SUCCESS(f"✓ تعرفه لیگ رهرو: {rahro_tariff.hourly_rate:,} تومان/ساعت"))

        rahro_group, _ = CustomerGroup.objects.get_or_create(
            name="لیگ رهرو",
            defaults={"tariff": rahro_tariff, "is_active": True, "edge_id": edge_id, "is_replica": False}
        )
        if rahro_group.tariff_id != rahro_tariff.id or not rahro_group.is_active:
            rahro_group.tariff = rahro_tariff
            rahro_group.is_active = True
            rahro_group.save(update_fields=["tariff", "is_active"])
        self.stdout.write(self.style.SUCCESS(f"✓ گروه لیگ رهرو: متصل به {rahro_tariff.name} ({rahro_tariff.hourly_rate:,} ت)"))

        # ۳. تعرفه و گروه کادر (۲۰ هزار تومان)
        cadre_tariff, _ = Tariff.objects.get_or_create(
            name="کادر",
            defaults={"hourly_rate": 20000, "is_active": True, "edge_id": edge_id, "is_replica": False}
        )
        if cadre_tariff.hourly_rate != 20000 or not cadre_tariff.is_active:
            cadre_tariff.hourly_rate = 20000
            cadre_tariff.is_active = True
            cadre_tariff.save(update_fields=["hourly_rate", "is_active"])
        self.stdout.write(self.style.SUCCESS(f"✓ تعرفه کادر: {cadre_tariff.hourly_rate:,} تومان/ساعت"))

        cadre_group, _ = CustomerGroup.objects.get_or_create(
            name="کادر",
            defaults={"tariff": cadre_tariff, "is_active": True, "edge_id": edge_id, "is_replica": False}
        )
        if cadre_group.tariff_id != cadre_tariff.id or not cadre_group.is_active:
            cadre_group.tariff = cadre_tariff
            cadre_group.is_active = True
            cadre_group.save(update_fields=["tariff", "is_active"])
        self.stdout.write(self.style.SUCCESS(f"✓ گروه کادر: متصل به {cadre_tariff.name} ({cadre_tariff.hourly_rate:,} ت)"))

        # ۴. بازتخصیص مشتریان به گروه‌های سه‌گانه معتبر
        allowed_group_ids = {free_group.id, rahro_group.id, cadre_group.id}
        for customer in Customer.objects.select_related("group").all():
            old_group_name = customer.group.name if customer.group else ""
            notes = customer.notes or ""
            target = None
            if any(k in old_group_name for k in ["کادر", "8", "9", "۸", "۹"]) or any(k in notes for k in ["کادر", "۲۰,۰۰۰", "20000"]):
                target = cadre_group
            elif any(k in old_group_name for k in ["رهرو", "لیگ", "5", "7", "۵", "۷"]) or any(k in notes for k in ["رهرو", "لیگ", "۴۰,۰۰۰", "40000"]):
                target = rahro_group
            elif customer.group_id not in allowed_group_ids:
                target = free_group

            if target and customer.group_id != target.id:
                customer.group = target
                customer.save(update_fields=["group", "updated_at"])
                self.stdout.write(f"  - مشتری {customer.full_name} -> گروه {target.name}")

        # ۵. بازتخصیص نشست‌ها به تعرفه‌های سه‌گانه
        allowed_tariff_ids = {free_tariff.id, rahro_tariff.id, cadre_tariff.id}
        for sess in GamingSession.objects.filter(tariff__isnull=False).select_related("tariff"):
            if sess.tariff_id not in allowed_tariff_ids:
                t_name = sess.tariff.name if sess.tariff else sess.tariff_name
                if "کادر" in t_name or "20" in t_name:
                    sess.tariff = cadre_tariff
                    sess.tariff_name = cadre_tariff.name
                elif "رهرو" in t_name or "40" in t_name:
                    sess.tariff = rahro_tariff
                    sess.tariff_name = rahro_tariff.name
                else:
                    sess.tariff = free_tariff
                    sess.tariff_name = free_tariff.name
                sess.save(update_fields=["tariff", "tariff_name"])

        # ۶. حذف گروه‌های قدیمی و اضافه
        extra_groups = CustomerGroup.objects.exclude(id__in=allowed_group_ids)
        deleted_g_count = extra_groups.count()
        if deleted_g_count > 0:
            extra_groups.delete()
            self.stdout.write(self.style.WARNING(f"✓ حذف {deleted_g_count} گروه اضافی/قدیمی"))

        # ۷. حذف تعرفه‌های قدیمی و اضافه
        extra_tariffs = Tariff.objects.exclude(id__in=allowed_tariff_ids)
        deleted_t_count = extra_tariffs.count()
        if deleted_t_count > 0:
            extra_tariffs.delete()
            self.stdout.write(self.style.WARNING(f"✓ حذف {deleted_t_count} تعرفه اضافی/قدیمی"))

        # ۸. به‌روزرسانی پیکربندی سراسری نرخ پیش‌فرض به ۶۰ هزار تومان
        try:
            for ac in AppliedConfig.objects.all():
                if ac.payload.get("default_hourly_rate") != 60000:
                    ac.payload["default_hourly_rate"] = 60000
                    ac.save(update_fields=["payload"])
        except Exception:
            pass

        try:
            active_cs = ConfigSnapshot.objects.filter(is_active=True).first()
            if active_cs and active_cs.payload.get("default_hourly_rate") != 60000:
                active_cs.payload["default_hourly_rate"] = 60000
                active_cs.content_hash = hashlib.sha256(
                    json.dumps(active_cs.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
                ).hexdigest()
                active_cs.save(update_fields=["payload", "content_hash"])
        except Exception:
            pass

        self.stdout.write(self.style.SUCCESS("✓ عملیات با موفقیت انجام شد: فقط ۳ تعرفه (آزاد: ۶۰,۰۰۰ت | لیگ رهرو: ۴۰,۰۰۰ت | کادر: ۲۰,۰۰۰ت) باقی ماندند."))
