from __future__ import annotations

from django.db import connection
from django.http import JsonResponse


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover - ops path
        return JsonResponse({"status": "error", "detail": str(exc)}, status=503)
    from django.conf import settings

    return JsonResponse(
        {
            "status": "ok",
            "role": settings.GAMENET_ROLE,
            "version": settings.GAMENET_VERSION,
        }
    )
