from django.apps import AppConfig


class SessionsConfig(AppConfig):
    """Our gaming-session module. The label must differ from Django's
    django.contrib.sessions, which is installed for admin authentication."""

    name = "apps.sessions"
    label = "gaming_sessions"
    verbose_name = "Gaming sessions"
    default_auto_field = "django.db.models.BigAutoField"
