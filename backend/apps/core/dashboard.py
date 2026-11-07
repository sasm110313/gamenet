"""Shared dashboard context for edge pages."""

from __future__ import annotations

from apps.core.roles import require_edge
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity, is_registered
from apps.synchronization.outbox import pending_counts


def edge_common() -> dict:
    require_edge()
    identity = ensure_identity()
    return {
        "identity": identity,
        "registered": is_registered(),
        "cloud_online": identity.status == "ONLINE",
        "last_sync": identity.last_sync_at,
        "counts": pending_counts(),
        "config": current_config(),
    }
