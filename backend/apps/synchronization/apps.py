from __future__ import annotations

import logging
import os
import sys
from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("gamenet.synchronization")


class SynchronizationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.synchronization"

    def ready(self):
        role = os.environ.get("GAMENET_ROLE", "edge")
        # Do not start sync worker thread during CLI management commands
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
        if getattr(settings, "GAMENET_ENV", "") == "test" or any("pytest" in arg for arg in sys.argv):
            return

        try:
            from apps.core.rahro import start_delivery_worker
            start_delivery_worker()
            if role != "edge":
                return
            from apps.synchronization.daemon import start_sync_daemon
            start_sync_daemon()
        except Exception as exc:
            logger.warning("Could not start background edge sync daemon: %s", exc)
