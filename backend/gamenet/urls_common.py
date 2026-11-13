from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from apps.core.views import healthz
from apps.core import views_errors

admin.site.site_header = "GameNet Control"
admin.site.site_title = "GameNet"
admin.site.index_title = "مدیریت"


def base_patterns() -> list:
    urlpatterns = [
        path("healthz", healthz, name="healthz"),
        path("admin/", admin.site.urls),
        path("errors/", views_errors.server_errors_page, name="server_errors_page"),
        path("api/v1/system/server-errors/", views_errors.server_errors_api, name="server_errors_api"),
        path("system/server-errors/download/", views_errors.download_server_errors_log, name="server_errors_download"),
    ]
    if settings.DEBUG:
        urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    return urlpatterns
