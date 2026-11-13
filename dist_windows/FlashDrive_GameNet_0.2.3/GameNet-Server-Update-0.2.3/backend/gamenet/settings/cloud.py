from .base import *  # noqa: F401,F403
from .base import env

GAMENET_ROLE = "cloud"
ROOT_URLCONF = "gamenet.urls_cloud"
CHANNEL_LAYER = env("CHANNEL_LAYER", default="redis")
if CHANNEL_LAYER == "redis":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [env("REDIS_URL", default="redis://127.0.0.1:56379/0")]},
        }
    }
else:  # single-process dev fallback
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
