from django.core.management.base import BaseCommand
import uuid
from apps.pricing.models import Tariff
from apps.customer_groups.models import CustomerGroup
from apps.synchronization.models import EdgeNode, EdgeIdentity


class Command(BaseCommand):
    help = "ایجاد و تثبیت تعرفه ۴۰,۰۰۰ تومان اعضای رهرو و تعرفه ۶۰,۰۰۰ تومان عادی"

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

        # ۱. تعرفه و گروه اعضای رهرو (۴۰ هزار تومان)
        rahro_tariff, created_t = Tariff.objects.get_or_create(
            name="تعرفه اعضای رهرو",
            edge_id=edge_id,
            defaults={"hourly_rate": 40000, "is_active": True, "is_replica": False}
        )
        if rahro_tariff.hourly_rate != 40000:
            rahro_tariff.hourly_rate = 40000
            rahro_tariff.save(update_fields=["hourly_rate"])
        self.stdout.write(self.style.SUCCESS(f"✓ تعرفه اعضای رهرو: {rahro_tariff.hourly_rate:,} تومان/ساعت"))

        rahro_group, created_g = CustomerGroup.objects.get_or_create(
            name="اعضای رهرو",
            edge_id=edge_id,
            defaults={"tariff": rahro_tariff, "is_active": True, "is_replica": False}
        )
        if rahro_group.tariff_id != rahro_tariff.id:
            rahro_group.tariff = rahro_tariff
            rahro_group.save(update_fields=["tariff"])
        self.stdout.write(self.style.SUCCESS(f"✓ گروه مشتریان: {rahro_group.name} -> متصل به تعرفه {rahro_tariff.hourly_rate:,} تومان"))

        # ۲. تعرفه و گروه عادی (۶۰ هزار تومان)
        normal_tariff, _ = Tariff.objects.get_or_create(
            name="عادی",
            edge_id=edge_id,
            defaults={"hourly_rate": 60000, "is_active": True, "is_replica": False}
        )
        if normal_tariff.hourly_rate != 60000:
            normal_tariff.hourly_rate = 60000
            normal_tariff.save(update_fields=["hourly_rate"])
        self.stdout.write(self.style.SUCCESS(f"✓ تعرفه عادی: {normal_tariff.hourly_rate:,} تومان/ساعت"))

        normal_group, _ = CustomerGroup.objects.get_or_create(
            name="عادی",
            edge_id=edge_id,
            defaults={"tariff": normal_tariff, "is_active": True, "is_replica": False}
        )
        if normal_group.tariff_id != normal_tariff.id:
            normal_group.tariff = normal_tariff
            normal_group.save(update_fields=["tariff"])
        self.stdout.write(self.style.SUCCESS(f"✓ گروه مشتریان: {normal_group.name} -> متصل به تعرفه {normal_tariff.hourly_rate:,} تومان"))
