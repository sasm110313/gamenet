from __future__ import annotations

import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.clients.models import ClientDevice, ClientStatus
from apps.core.ids import uuid7
from apps.core.roles import require_edge
from apps.pricing.models import Tariff
from apps.synchronization.edge_credentials import ensure_identity


class Command(BaseCommand):
    help = "Bootstrap local salon edge database with admin user, default tariff, and 10 PC stations."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=os.environ.get("ADMIN_USERNAME", "admin"))
        parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", "admin123"))
        parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", "admin@gamenet.local"))

    @transaction.atomic
    def handle(self, *args, **options):
        require_edge()
        User = get_user_model()
        username = options["username"]
        password = options["password"]
        email = options["email"]

        # 1. Ensure Edge identity
        identity = ensure_identity()
        self.stdout.write(self.style.SUCCESS(f"Edge identity: {identity.edge_id} ({identity.name})"))

        # 2. Ensure superuser exists (does not overwrite custom admin usernames)
        user = User.objects.filter(username=username).first()
        if user is None:
            if User.objects.filter(is_superuser=True).exists():
                self.stdout.write("Superuser already configured with custom username.")
            else:
                user = User.objects.create_superuser(
                    username=username,
                    password=password,
                    email=email,
                    display_name="مدیر سالن",
                )
                self.stdout.write(self.style.SUCCESS(f"Created admin user: {username} (pass: {password})"))
        else:
            self.stdout.write(f"Admin user {username} already exists.")

        # 3. Ensure default salon tariffs exist (آزاد 60k, لیگ رهرو 40k, کادر 20k)
        tariff = Tariff.objects.filter(is_active=True).first()
        if tariff is None:
            from django.core.management import call_command

            call_command("ensure_rahro_pricing")
            tariff = Tariff.objects.filter(is_active=True).first()
            self.stdout.write(self.style.SUCCESS(f"Initialized default salon tariffs (active: {tariff.name if tariff else '-'})"))
        else:
            self.stdout.write(f"Active tariff: {tariff.name} ({tariff.hourly_rate:,} Tomans/hr)")

        # 4. Ensure 10 standard PC stations (PC-01 to PC-10) exist
        created_devices = 0
        for i in range(1, 11):
            name = f"PC-{i:02d}"
            device, is_new = ClientDevice.objects.get_or_create(
                name=name,
                defaults={
                    "id": uuid7(),
                    "edge_id": identity.edge_id,
                    "hostname": name.lower(),
                    "operating_system": "Windows",
                    "status": ClientStatus.OFFLINE,
                    "is_active": True,
                },
            )
            if is_new:
                created_devices += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Client stations initialized: 10 stations (PC-01 to PC-10). {created_devices} new stations added."
            )
        )
