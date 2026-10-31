import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gamenet.settings.dev")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.core.ws import TokenOriginValidator, allowed_origin_patterns  # noqa: E402
from gamenet.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": TokenOriginValidator(
            URLRouter(websocket_urlpatterns), allowed_origin_patterns()
        ),
    }
)
