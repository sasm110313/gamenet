from __future__ import annotations

import logging
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin
from apps.core.error_logging import record_server_error

logger = logging.getLogger("gamenet.middleware.errors")


class GlobalErrorCaptureMiddleware(MiddlewareMixin):
    """Intercepts unhandled server exceptions, logs full traceback to server_errors.log,

    and returns a structured JSON or styled HTML 500 error page with copy button.
    """

    def process_exception(self, request, exception):
        # Record into error logging system and file
        entry = record_server_error(request, exception)
        logger.error(
            "Captured unhandled exception at %s %s: %s",
            request.method,
            request.path,
            exception,
            exc_info=exception,
        )

        is_api = (
            request.path.startswith("/api/")
            or request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "").lower()
            or request.content_type == "application/json"
        )

        if is_api:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "internal_server_error",
                        "error_id": entry["id"],
                        "type": entry["error_type"],
                        "message": entry["message"] or "خطای پیش‌بینی‌نشده در سرور گیم‌نت رخ داد.",
                        "traceback": entry["traceback"],
                    },
                },
                status=500,
            )

        # For normal browser navigation, render 500 template with full traceback and copy button
        try:
            return render(
                request,
                "500.html",
                {
                    "error_entry": entry,
                    "error_id": entry["id"],
                    "error_type": entry["error_type"],
                    "error_message": entry["message"],
                    "traceback": entry["traceback"],
                },
                status=500,
            )
        except Exception:
            # Fallback if 500 template fails
            return None
