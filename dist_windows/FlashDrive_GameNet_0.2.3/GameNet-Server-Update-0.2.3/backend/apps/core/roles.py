"""Role helpers. A cloud process must never act like an edge, and vice versa."""

from __future__ import annotations

from django.conf import settings


class WrongRole(RuntimeError):
    pass


def role() -> str:
    return settings.GAMENET_ROLE


def is_cloud() -> bool:
    return role() == "cloud"


def is_edge() -> bool:
    return role() == "edge"


def require_edge() -> None:
    if not is_edge():
        raise WrongRole(f"edge-only code path reached in role={role()!r}")


def require_cloud() -> None:
    if not is_cloud():
        raise WrongRole(f"cloud-only code path reached in role={role()!r}")
