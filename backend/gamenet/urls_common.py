from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from apps.core.views import healthz

admin.site.site_header = "GameNet Control"
admin.site.site_title = "GameNet"
admin.site.index_title = "مدیریت"


def base_patterns() -> list:
    urlpatterns = [
        path("healthz", healthz, name="healthz"),
        path("admin/", admin.site.urls),
    ]
    if settings.DEBUG:
        urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    return urlpatterns
