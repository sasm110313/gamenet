from __future__ import annotations

from django.conf import settings


def role_context(request):
    is_edge = settings.GAMENET_ROLE == "edge"
    cloud_online = False
    if is_edge:
        try:
            from apps.synchronization.models import EdgeIdentity

            status = EdgeIdentity.objects.filter(pk=1).values_list("status", flat=True).first()
            cloud_online = status == "ONLINE"
        except Exception:
            cloud_online = False
    return {
        "gamenet_role": settings.GAMENET_ROLE,
        "gamenet_version": settings.GAMENET_VERSION,
        "is_cloud": settings.GAMENET_ROLE == "cloud",
        "is_edge": is_edge,
        "cloud_online": cloud_online,
    }
