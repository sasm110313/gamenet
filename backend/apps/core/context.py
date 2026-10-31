from __future__ import annotations

from django.conf import settings


def role_context(request):
    return {
        "gamenet_role": settings.GAMENET_ROLE,
        "gamenet_version": settings.GAMENET_VERSION,
        "is_cloud": settings.GAMENET_ROLE == "cloud",
        "is_edge": settings.GAMENET_ROLE == "edge",
    }
