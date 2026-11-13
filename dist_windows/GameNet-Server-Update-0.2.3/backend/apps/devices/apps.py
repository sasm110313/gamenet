from __future__ import annotations

import logging
import os
from django.apps import AppConfig

logger = logging.getLogger("gamenet.devices")


class DevicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.devices"

    def ready(self):
        role = os.environ.get("GAMENET_ROLE", "edge")
        if role == "edge":
            import sys
            cli_commands_to_skip = {
                "migrate",
                "makemigrations",
                "showmigrations",
                "collectstatic",
                "createsuperuser",
                "change_admin",
                "check",
                "shell",
                "dbshell",
                "test",
                "edge_register",
                "run_edge_worker",
                "bootstrap_edge",
                "inspectdb",
                "dumpdata",
                "loaddata",
            }
            if any(cmd in sys.argv for cmd in cli_commands_to_skip):
                return
            try:
                from apps.devices.discovery import start_discovery_service
                start_discovery_service()
            except Exception as exc:
                logger.warning("Could not start LAN discovery service: %s", exc)
