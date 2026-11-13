from django.apps import AppConfig


class CustomersConfig(AppConfig):
    name = "apps.customers"
    verbose_name = "Customers"
    default_auto_field = "django.db.models.BigAutoField"
