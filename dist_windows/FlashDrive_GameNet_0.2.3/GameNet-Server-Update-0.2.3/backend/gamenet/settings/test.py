"""Test settings: fast password hashing, eager sync, temp credentials path."""

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, env  # noqa: F401

GAMENET_ENV = "test"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
ROOT_URLCONF = "gamenet.urls_edge"
# Static files are irrelevant to API/consumer tests; skip the whitenoise warning.
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]

# Never inherit the developer's .env database: tests get their own DSN and name.
DATABASES = {
    "default": env.db_url(
        "TEST_DATABASE_URL",
        default="postgresql://gamenet:gamenet@127.0.0.1:55432/gamenet_test",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = 0
EDGE_CREDENTIALS_FILE = str(BASE_DIR / ".pytest-artifacts" / "edge-credentials.json")
CLOUD_BASE_URL = "http://cloud.test"
SYNC_BATCH_SIZE = 10
SECURE_SSL_REDIRECT = False
