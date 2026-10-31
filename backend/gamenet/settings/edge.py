from .base import *  # noqa: F401,F403
from .base import env

GAMENET_ROLE = "edge"
ROOT_URLCONF = "gamenet.urls_edge"
# Redis is not available natively on Windows. The edge runs exactly one ASGI
# worker with an in-process layer, enforced by apps.core.checks.
CHANNEL_LAYER = env("CHANNEL_LAYER", default="memory")
if CHANNEL_LAYER == "redis":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [env("REDIS_URL", default="redis://127.0.0.1:56379/0")]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
