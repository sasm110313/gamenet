from __future__ import annotations

import logging

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpRequest

from apps.clients.models import ClientDevice
from apps.core.security import constant_time_equal
from apps.synchronization.crypto import hash_token
from apps.synchronization.models import EdgeNode, EdgeStatus

logger = logging.getLogger("gamenet.auth")


def bearer_parts(header: str, scheme: str) -> tuple[str, str] | None:
    if not header or not header.startswith(f"{scheme} "):
        return None
    raw = header[len(scheme) + 1 :].strip()
    identity, _, secret = raw.partition(".")
    if not identity or not secret:
        return None
    return identity, secret


def authenticate_edge_header(header: str) -> EdgeNode | None:
    parts = bearer_parts(header, "Edge")
    if parts is None:
        return None
    edge_id, secret = parts
    try:
        edge = EdgeNode.objects.filter(pk=edge_id).first()
    except (ValueError, TypeError, DatabaseError):
        return None
    if edge is None or edge.status == EdgeStatus.REVOKED:
        return None
    if not constant_time_equal(edge.secret_hash, hash_token(secret)):
        return None
    return edge


def authenticate_device_header(header: str) -> ClientDevice | None:
    parts = bearer_parts(header, "Device")
    if parts is None:
        return None
    device_id, token = parts
    from apps.devices.services import authenticate_device

    device = authenticate_device(device_id, token)
    if device is None:
        return None
    # A device paired to one edge must never be accepted by another edge's DB.
    from apps.synchronization.models import EdgeIdentity

    try:
        identity = EdgeIdentity.get_solo()
    except EdgeIdentity.DoesNotExist:
        return None
    if device.edge_id != identity.edge_id or not device.is_active:
        return None
    return device


def client_ip(request: HttpRequest) -> str | None:
    # No proxy in front of the edge by default; do not trust X-Forwarded-For here.
    return request.META.get("REMOTE_ADDR")


def cloud_ws_url(request: HttpRequest) -> str:
    """Absolute WSS base for this cloud deployment (env-driven, never hardcoded)."""
    if settings.CLOUD_WS_URL:
        return settings.CLOUD_WS_URL.rstrip("/")
    return ""
