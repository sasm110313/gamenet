from __future__ import annotations

from django.urls import path

from apps.customers import dashboard as customers_dash
from apps.devices import dashboard as dash
from apps.devices import views as api
from apps.ledger import dashboard as ledger_dash
from apps.pricing import dashboard as pricing_dash
from apps.sessions import dashboard as sessions_dash
from gamenet.urls_common import base_patterns

urlpatterns = [
    path("", dash.overview, name="edge_overview"),
    path("customers/", customers_dash.customers, name="edge_customers"),
    path("customers/create", customers_dash.customer_create, name="edge_customer_create"),
    path("customers/<uuid:customer_id>/", customers_dash.customer_detail, name="edge_customer_detail"),
    path("customers/<uuid:customer_id>/update", customers_dash.customer_update, name="edge_customer_update"),
    path("customers/<uuid:customer_id>/toggle", customers_dash.customer_toggle, name="edge_customer_toggle"),
    path("customers/<uuid:customer_id>/deposit", customers_dash.customer_deposit, name="edge_customer_deposit"),
    path("customers/<uuid:customer_id>/adjust", customers_dash.customer_adjust, name="edge_customer_adjust"),
    path(
        "customers/<uuid:customer_id>/reverse/<uuid:entry_id>",
        customers_dash.customer_reverse,
        name="edge_customer_reverse",
    ),
    path("sessions/", sessions_dash.sessions, name="edge_sessions"),
    path("sessions/start", sessions_dash.session_start, name="edge_session_start"),
    path("sessions/<uuid:session_id>/stop", sessions_dash.session_stop, name="edge_session_stop"),
    path("ledger/", ledger_dash.ledger, name="edge_ledger"),
    path("pricing/", pricing_dash.pricing, name="edge_pricing"),
    path("pricing/tariffs/create", pricing_dash.tariff_create, name="edge_tariff_create"),
    path(
        "pricing/tariffs/<uuid:tariff_id>/update",
        pricing_dash.tariff_update,
        name="edge_tariff_update",
    ),
    path("pricing/groups/create", pricing_dash.group_create, name="edge_group_create"),
    path(
        "pricing/groups/<uuid:group_id>/update",
        pricing_dash.group_update,
        name="edge_group_update",
    ),
    path("devices/", dash.devices, name="edge_devices"),
    path("devices/grid", dash.device_grid, name="edge_device_grid"),
    path("devices/<uuid:device_id>/", dash.device_detail, name="edge_device_detail"),
    path("devices/<uuid:device_id>/action", dash.device_action, name="edge_device_action"),
    path("devices/<uuid:device_id>/deactivate", dash.deactivate, name="edge_device_deactivate"),
    path("codes/create", dash.create_code, name="edge_create_code"),
    path("cloud/", dash.cloud_health, name="edge_cloud"),
    path("cloud/retry", dash.cloud_retry, name="edge_cloud_retry"),
    path("cloud/register", dash.cloud_register, name="edge_cloud_register"),
    path("cloud/test-event", dash.emit_test, name="edge_emit_test"),
    # client-facing API
    path("api/v1/device/register", api.DeviceRegisterView.as_view(), name="api_device_register"),
    path("api/v1/device/heartbeat", api.DeviceHeartbeatView.as_view(), name="api_device_heartbeat"),
    path("api/v1/device/me", api.DeviceMeView.as_view(), name="api_device_me"),
    path("api/v1/device/commands/pending", api.DeviceCommandsPendingView.as_view(), name="api_device_commands"),
    path(
        "api/v1/device/commands/<uuid:command_id>/ack",
        api.DeviceCommandAckView.as_view(),
        name="api_device_command_ack",
    ),
] + base_patterns()
