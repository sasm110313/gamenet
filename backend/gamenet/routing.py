from django.conf import settings
from django.urls import path

if settings.GAMENET_ROLE == "cloud":
    from apps.ingress.consumers import EdgeConsumer

    websocket_urlpatterns = [path("ws/edge/", EdgeConsumer.as_asgi())]
else:
    from apps.devices.consumers import DeviceConsumer

    websocket_urlpatterns = [path("ws/device/", DeviceConsumer.as_asgi())]
