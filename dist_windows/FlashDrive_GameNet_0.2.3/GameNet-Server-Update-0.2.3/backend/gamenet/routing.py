from django.conf import settings
from django.urls import path

from apps.devices.remote_ws import RemoteViewerConsumer

if settings.GAMENET_ROLE == "cloud":
    from apps.ingress.consumers import EdgeConsumer

    websocket_urlpatterns = [
        path("ws/edge/", EdgeConsumer.as_asgi()),
        path("ws/remote/<uuid:device_id>/", RemoteViewerConsumer.as_asgi()),
    ]
else:
    from apps.devices.consumers import DeviceConsumer

    websocket_urlpatterns = [
        path("ws/device/", DeviceConsumer.as_asgi()),
        path("ws/remote/<uuid:device_id>/", RemoteViewerConsumer.as_asgi()),
    ]
