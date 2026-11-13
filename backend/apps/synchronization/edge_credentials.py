"""Edge identity + cloud credential lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.core.roles import require_edge
from apps.synchronization.models import EdgeIdentity
from apps.synchronization.secure_store import SecureStore


@dataclass(frozen=True)
class EdgeCredentials:
    edge_id: str
    secret: str
    base_url: str
    command_public_key: str


def store() -> SecureStore:
    return SecureStore(settings.EDGE_CREDENTIALS_FILE)


def ensure_identity() -> EdgeIdentity:
    """Create the local edge identity on first use.

    The UUID is generated locally at install time and stays stable for the life of
    the install (including before the site is paired with the cloud), so outbox
    events recorded offline keep the same edge_id forever.
    """
    require_edge()
    identity = EdgeIdentity.objects.filter(pk=1).first()
    if identity is not None:
        return identity
    from apps.core.ids import uuid7

    EdgeIdentity.objects.get_or_create(
        pk=1,
        defaults={
            "edge_id": uuid7(),
            "name": settings.EDGE_NAME,
            "cloud_base_url": settings.CLOUD_BASE_URL or "http://unregistered.invalid",
            "credential_reference": str(Path(settings.EDGE_CREDENTIALS_FILE)),
            "command_public_key": "",
        },
    )
    return EdgeIdentity.objects.get(pk=1)


def is_registered() -> bool:
    return EdgeIdentity.objects.exists() and store().exists()


def load_credentials() -> EdgeCredentials:
    require_edge()
    identity = EdgeIdentity.get_solo()
    data = store().load()
    if data.get("edge_id") != str(identity.edge_id):
        raise RuntimeError("credential file does not match the edge identity in the database")
    return EdgeCredentials(
        edge_id=str(identity.edge_id),
        secret=data["secret"],
        base_url=identity.cloud_base_url or data.get("base_url") or settings.CLOUD_BASE_URL,
        command_public_key=identity.command_public_key,
    )


def save_registration(*, edge_id: str, secret: str, name: str, base_url: str,
                      public_key: str, software_version: str) -> EdgeIdentity:
    require_edge()
    store().save({"edge_id": edge_id, "secret": secret, "base_url": base_url})
    identity, _ = EdgeIdentity.objects.update_or_create(
        pk=1,
        defaults={
            "edge_id": edge_id,
            "name": name,
            "cloud_base_url": base_url,
            "credential_reference": str(Path(settings.EDGE_CREDENTIALS_FILE)),
            "command_public_key": public_key,
            "software_version": software_version,
        },
    )
    return identity


def clear_registration() -> None:
    EdgeIdentity.objects.all().delete()
    store().delete()
