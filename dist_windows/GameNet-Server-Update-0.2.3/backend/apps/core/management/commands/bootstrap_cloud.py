from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.roles import require_cloud
from apps.synchronization.models import ConfigSnapshot, EdgeRegistrationCode


class Command(BaseCommand):
    help = "Create the admin account and initial configuration snapshot (cloud only)."

    def add_arguments(self, parser):
        parser.add_argument("--code", action="store_true", help="also print a new edge registration code")
        parser.add_argument("--username", default=os.environ.get("ADMIN_USERNAME", "admin"))
        parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
        parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", ""))

    @transaction.atomic
    def handle(self, *args, **options):
        require_cloud()
        User = get_user_model()
        username = options["username"]
        password = options["password"]

        user = User.objects.filter(username=username).first()
        if user is None:
            if User.objects.filter(is_superuser=True).exists():
                user = User.objects.filter(is_superuser=True).first()
                self.stdout.write("Superuser already configured with custom username.")
            else:
                if not password:
                    raise SystemExit("ADMIN_PASSWORD (or --password) is required to create the admin")
                user = User.objects.create_superuser(username=username, password=password,
                                                     email=options["email"])
                self.stdout.write(self.style.SUCCESS(f"created admin {username}"))
        else:
            self.stdout.write(f"admin {username} already exists")

        if not ConfigSnapshot.objects.exists():
            payload = {
                "device_heartbeat_seconds": 10,
                "device_offline_after_missed": 3,
                "default_hourly_rate": 40_000,
                "default_credit_limit": 60_000,
                "command_ttl_seconds": 120,
            }
            content_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()
            ConfigSnapshot.objects.create(version=1, payload=payload, content_hash=content_hash,
                                          created_by=user)
            self.stdout.write(self.style.SUCCESS("created config snapshot v1"))

        if options["code"]:
            code = "".join(
                secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8)
            )
            reg = EdgeRegistrationCode.objects.create(
                code=code,
                note="cli bootstrap",
                created_by=user,
                expires_at=timezone.now() + timedelta(hours=24),
            )
            self.stdout.write(self.style.WARNING(f"EDGE_REGISTRATION_CODE={reg.code}"))
