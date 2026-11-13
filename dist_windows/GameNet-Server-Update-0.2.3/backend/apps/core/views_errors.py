from __future__ import annotations

import os
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from apps.core.error_logging import clear_recent_errors, get_recent_errors, _log_file_path


@login_required
def server_errors_page(request):
    """HTML page showing the recent server errors with tracebacks and 1-click copy."""
    errors = get_recent_errors(50)
    log_file = _log_file_path()
    file_exists = os.path.exists(log_file)
    file_size = os.path.getsize(log_file) if file_exists else 0

    return render(
        request,
        "core/server_errors.html",
        {
            "errors": errors,
            "log_file_path": log_file,
            "file_size": file_size,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def server_errors_api(request):
    """API endpoint to fetch or clear recent server errors."""
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "clear":
            clear_recent_errors()
            return JsonResponse({"ok": True, "message": "لاگ خطاها پاک شد."})

    errors = get_recent_errors(50)
    return JsonResponse({"ok": True, "errors": errors, "count": len(errors)})


@login_required
def download_server_errors_log(request):
    """Download the raw server_errors.log file."""
    log_path = _log_file_path()
    if not os.path.exists(log_path):
        return HttpResponse("هیچ خطایی تا کنون ثبت نشده است.", content_type="text/plain; charset=utf-8")

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="server_errors.log"'
    return response
