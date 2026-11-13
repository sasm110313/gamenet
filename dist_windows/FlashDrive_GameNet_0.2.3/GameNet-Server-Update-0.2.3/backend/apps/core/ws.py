from __future__ import annotations

from channels.security.websocket import OriginValidator
from django.conf import settings


def allowed_origin_patterns() -> list[str]:
    return [host for host in settings.ALLOWED_HOSTS if host != "*"]


class TokenOriginValidator(OriginValidator):
    """Origin checks for token-authenticated sockets.

    Browser clients send Origin and must match an allowed host. Programmatic
    clients (the edge tunnel, the Electron main process) send no Origin; they are
    authenticated by a bearer token in the first frame, not by cookies, so CSWSH
    does not apply and a missing Origin is acceptable.
    """

    def valid_origin(self, parsed_origin):
        if parsed_origin is None:
            return True
        return super().valid_origin(parsed_origin)
