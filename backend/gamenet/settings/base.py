"""Base settings shared by the cloud and the edge.

The two roles run the *same* project and the *same* migrations. Only transport
wiring, channel layer and runtime knobs differ (see settings/cloud.py, edge.py).
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BASE_DIR.parent

env = environ.Env()
environ.Env.read_env(ROOT_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    raise SystemExit("DJANGO_SECRET_KEY is not set. Copy .env.example to .env.")

DEBUG = env.bool("DJANGO_DEBUG", default=False)
GAMENET_ROLE = env("GAMENET_ROLE", default="edge")
if GAMENET_ROLE not in {"cloud", "edge"}:
    raise SystemExit(f"GAMENET_ROLE must be cloud|edge, got {GAMENET_ROLE!r}")
GAMENET_ENV = env("GAMENET_ENV", default="dev")
GAMENET_VERSION = "0.2.0-phase2"

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
USE_X_FORWARDED_HOST = env.bool("DJANGO_USE_X_FORWARDED_HOST", default=False)
if env.bool("DJANGO_BEHIND_PROXY", default=False):
    # Nginx terminates TLS and forwards X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Applications -----------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    # business modules
    "apps.core",
    "apps.accounts",
    "apps.customers",
    "apps.customer_groups",
    "apps.pricing",
    "apps.wallets",
    "apps.ledger",
    "apps.sessions",
    "apps.clients",
    "apps.applications",
    "apps.commands",
    "apps.synchronization",
    "apps.reports",
    "apps.audit",
    # transport modules (schemas identical in both roles; guards enforce role)
    "apps.ingress",
    "apps.devices",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "gamenet.urls_cloud"  # overridden per role

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context.role_context",
            ],
        },
    },
]

WSGI_APPLICATION = "gamenet.wsgi.application"
ASGI_APPLICATION = "gamenet.asgi.application"

# --- Database ---------------------------------------------------------------
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default="postgresql://gamenet:gamenet@127.0.0.1:55432/gamenet_edge",
    )
}
DATABASES["default"].setdefault("CONN_MAX_AGE", 60)
if "postgresql" in DATABASES["default"].get("ENGINE", ""):
    DATABASES["default"].setdefault(
        "OPTIONS", {"connect_timeout": 5, "application_name": f"gamenet-{GAMENET_ROLE}"}
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n -------------------------------------------------------------------
LANGUAGE_CODE = "fa"
LANGUAGES = [("fa", "فارسی"), ("en", "English")]
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

# --- Static ----------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT", default=str(ROOT_DIR / ".artifacts" / "static")))
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --- Sessions / cookies -----------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=False)
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=False)
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)

# --- DRF --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler",
    "DEFAULT_THROTTLE_RATES": {"registration": "20/min"},
}

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "gamenet"}
}

# --- Channels ---------------------------------------------------------------
CHANNEL_LAYER = env("CHANNEL_LAYER", default="memory")
if CHANNEL_LAYER == "redis":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [env("REDIS_URL", default="redis://127.0.0.1:6379/0")]},
        }
    }
else:
    # Single-process ASGI only. Enforced at startup for the edge role.
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# --- Edge runtime -----------------------------------------------------------
EDGE_NAME = env("EDGE_NAME", default="Main Gaming Floor")
EDGE_REGISTRATION_CODE = env("EDGE_REGISTRATION_CODE", default="")
EDGE_LAN_BIND = env("EDGE_LAN_BIND", default="0.0.0.0")
EDGE_LAN_PORT = env.int("EDGE_LAN_PORT", default=9443)
EDGE_CREDENTIALS_FILE = env(
    "EDGE_CREDENTIALS_FILE", default=str(ROOT_DIR / ".artifacts" / "edge-credentials.json")
)
if not Path(EDGE_CREDENTIALS_FILE).is_absolute():
    EDGE_CREDENTIALS_FILE = str(ROOT_DIR / EDGE_CREDENTIALS_FILE)
CLOUD_BASE_URL = env("CLOUD_BASE_URL", default="https://gamenet.hammasjedy.ir").rstrip("/")
CLOUD_WS_URL = env("CLOUD_WS_URL", default="wss://gamenet.hammasjedy.ir/ws/edge/").rstrip("/")
CLOUD_CA_BUNDLE = env("CLOUD_CA_BUNDLE", default="")
if CLOUD_CA_BUNDLE and not Path(CLOUD_CA_BUNDLE).is_absolute():
    CLOUD_CA_BUNDLE = str(ROOT_DIR / CLOUD_CA_BUNDLE)
EDGE_SYNC_INTERVAL_SECONDS = env.int("EDGE_SYNC_INTERVAL_SECONDS", default=2)
EDGE_HEARTBEAT_SECONDS = env.int("EDGE_HEARTBEAT_SECONDS", default=15)
EDGE_REQUEST_TIMEOUT_SECONDS = env.int("EDGE_REQUEST_TIMEOUT_SECONDS", default=10)

# --- Device protocol --------------------------------------------------------
DEVICE_HEARTBEAT_SECONDS = env.int("DEVICE_HEARTBEAT_SECONDS", default=10)
DEVICE_OFFLINE_AFTER_MISSED = env.int("DEVICE_OFFLINE_AFTER_MISSED", default=3)
DEVICE_REGISTRATION_CODE_TTL_MINUTES = env.int("DEVICE_REGISTRATION_CODE_TTL_MINUTES", default=30)
DEVICE_COMMAND_TTL_SECONDS = env.int("DEVICE_COMMAND_TTL_SECONDS", default=120)

# --- Sync protocol ----------------------------------------------------------
SYNC_BATCH_SIZE = env.int("SYNC_BATCH_SIZE", default=100)
SYNC_MAX_ATTEMPTS_BEFORE_BACKOFF = env.int("SYNC_MAX_ATTEMPTS_BEFORE_BACKOFF", default=12)
SYNC_SCHEMA_VERSION = 1
COMMAND_CLOCK_SKEW_SECONDS = env.int("COMMAND_CLOCK_SKEW_SECONDS", default=60)

# --- Money defaults ---------------------------------------------------------
DEFAULT_HOURLY_RATE = env.int("DEFAULT_HOURLY_RATE", default=60_000)  # Toman (تعرفه عادی غیر رهرو)
DEFAULT_CREDIT_LIMIT = env.int("DEFAULT_CREDIT_LIMIT", default=60_000)  # Toman

# --- Rahro Integration -----------------------------------------------------
RAHRO_GAMENET_SHARED_SECRET = env("RAHRO_GAMENET_SHARED_SECRET", default="rahro_gamenet_secret_2026")
RAHRO_API_URL = env("RAHRO_API_URL", default="http://127.0.0.1:8000/rahro/api/gamenet/")

# --- Security ---------------------------------------------------------------
if not DEBUG:
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "loggers": {
        "gamenet": {"handlers": ["console"], "level": env("GAMENET_LOG_LEVEL", default="INFO")},
        "django.request": {"handlers": ["console"], "level": "WARNING"},
        "django.security": {"handlers": ["console"], "level": "DEBUG"},
    },
}

# --- Testing hooks ----------------------------------------------------------
TESTING = os.environ.get("PYTEST_CURRENT_TEST") is not None
