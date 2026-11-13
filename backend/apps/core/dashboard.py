"""Shared dashboard context for edge pages."""

from __future__ import annotations

from apps.core.roles import require_edge
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity, is_registered
from apps.synchronization.outbox import pending_counts


def edge_common() -> dict:
    require_edge()
    identity = ensure_identity()
    from apps.devices.discovery import get_primary_lan_ip, get_interface_pairs
    ips = [ip for ip, _ in get_interface_pairs() if not ip.startswith("127.")]
    primary_ip = get_primary_lan_ip()
    return {
        "identity": identity,
        "registered": is_registered(),
        "cloud_online": identity.status == "ONLINE",
        "last_sync": identity.last_sync_at,
        "counts": pending_counts(),
        "config": current_config(),
        "edge_primary_ip": primary_ip,
        "edge_lan_ips": ips,
    }
