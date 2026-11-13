from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.roles import require_edge
from apps.synchronization.cloud_client import CloudClient
from apps.synchronization.edge_credentials import ensure_identity, save_registration


class Command(BaseCommand):
    help = "Pair this edge with the cloud using a one-time registration code."

    def add_arguments(self, parser):
        parser.add_argument("--code", required=True)
        parser.add_argument("--name", default=None)

    def handle(self, *args, **options):
        require_edge()
        identity = ensure_identity()
        response = CloudClient.register(
            base_url=settings.CLOUD_BASE_URL,
            code=options["code"],
            name=options["name"] or identity.name,
            software_version=settings.GAMENET_VERSION,
            ca_bundle=settings.CLOUD_CA_BUNDLE,
            edge_id=str(identity.edge_id),
        )
        save_registration(
            edge_id=response["edge_id"],
            secret=response["secret"],
            name=options["name"] or identity.name,
            base_url=settings.CLOUD_BASE_URL,
            public_key=response["command_public_key"],
            software_version=settings.GAMENET_VERSION,
        )
        self.stdout.write(
            self.style.SUCCESS(
                json.dumps(
                    {
                        "edge_id": response["edge_id"],
                        "config_version": response.get("config_version"),
                        "ws_path": response.get("ws_path"),
                    },
                    indent=2,
                )
            )
        )
