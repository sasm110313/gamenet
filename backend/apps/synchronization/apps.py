from __future__ import annotations

import logging
import os
import sys
from django.apps import AppConfig

logger = logging.getLogger("gamenet.synchronization")


class SynchronizationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.synchronization"

    def ready(self):
        role = os.environ.get("GAMENET_ROLE", "edge")
        if role != "edge":
            return

        # Do not start sync worker thread during CLI management commands
        cli_commands_to_skip = {
            "migrate",
            "makemigrations",
            "collectstatic",
            "createsuperuser",
            "shell",
            "test",
            "edge_register",
            "run_edge_worker",
            "bootstrap_edge",
            "inspectdb",
        }
        if any(cmd in sys.argv for cmd in cli_commands_to_skip):
            return

        try:
            from apps.synchronization.daemon import start_sync_daemon
            start_sync_daemon()
        except Exception as exc:
            logger.warning("Could not start background edge sync daemon: %s", exc)
