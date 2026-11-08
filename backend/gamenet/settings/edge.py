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

# Zero-setup SQLite default for Windows edge if no DATABASE_URL is explicitly set
if "DATABASE_URL" not in os.environ:
    sqlite_path = BASE_DIR / "data" / "gamenet_edge.sqlite3"
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(sqlite_path),
        "CONN_MAX_AGE": 60,
    }
