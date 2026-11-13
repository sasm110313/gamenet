from __future__ import annotations

from django.urls import path

from apps.accounts import views as account_views
from apps.customers import dashboard as customers_dash
from apps.devices import dashboard as dash
from apps.devices import views as api
from apps.applications import views as app_views
from apps.core import views_announcements as ann_views
from apps.ledger import dashboard as ledger_dash
from apps.pricing import dashboard as pricing_dash
from apps.sessions import dashboard as sessions_dash
from gamenet.urls_common import base_patterns

urlpatterns = [
    path("", dash.overview, name="edge_overview"),
    path("account/", account_views.account_settings, name="edge_account"),
    path("announcements/", ann_views.announcements_list, name="edge_announcements"),
    path("api/v1/announcements/", ann_views.api_announcements, name="api_announcements"),
    path("games/", app_views.games_list, name="edge_games"),
    path("api/v1/games/", app_views.api_games_catalog, name="api_games_catalog"),
    path("customers/", customers_dash.customers, name="edge_customers"),
    path("customers/create", customers_dash.customer_create, name="edge_customer_create"),
    path("customers/create/", customers_dash.customer_create),
    path("customers/<uuid:customer_id>/", customers_dash.customer_detail, name="edge_customer_detail"),
    path("customers/<uuid:customer_id>/update", customers_dash.customer_update, name="edge_customer_update"),
    path(
        "customers/<uuid:customer_id>/rahro-discount",
        customers_dash.customer_rahro_discount,
        name="edge_customer_rahro_discount",
    ),
    path(
        "customers/<uuid:customer_id>/recharge",
        customers_dash.customer_rahro_recharge,
        name="edge_customer_rahro_recharge",
    ),
    path("customers/<uuid:customer_id>/toggle", customers_dash.customer_toggle, name="edge_customer_toggle"),
    path("customers/<uuid:customer_id>/deposit", customers_dash.customer_deposit, name="edge_customer_deposit"),
    path("customers/<uuid:customer_id>/settle-debt", customers_dash.customer_settle_debt, name="edge_customer_settle_debt"),
    path("customers/<uuid:customer_id>/adjust", customers_dash.customer_adjust, name="edge_customer_adjust"),
    path(
        "customers/<uuid:customer_id>/rates/create",
        customers_dash.customer_rate_create,
        name="edge_customer_rate_create",
    ),
    path(
        "customers/<uuid:customer_id>/rates/<uuid:rate_id>/update",
        customers_dash.customer_rate_update,
        name="edge_customer_rate_update",
    ),
    path(
        "customers/<uuid:customer_id>/rates/<uuid:rate_id>/default",
        customers_dash.customer_rate_default,
        name="edge_customer_rate_default",
    ),
    path(
        "customers/<uuid:customer_id>/rates/<uuid:rate_id>/deactivate",
        customers_dash.customer_rate_deactivate,
        name="edge_customer_rate_deactivate",
    ),
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
    path("devices/create", dash.device_create, name="edge_device_create"),
    path("server/remote/", dash.server_remote, name="edge_server_remote"),
    path("server/remote/rdp-file", dash.server_remote_file, name="edge_server_remote_file"),
    path("server/remote/enable", dash.server_remote_enable, name="edge_server_remote_enable"),
    path("devices/trigger-update-clients", dash.edge_trigger_clients_update, name="edge_trigger_clients_update"),
    path("devices/bulk-action", dash.devices_bulk_action, name="edge_devices_bulk_action"),
    path("devices/stations-partial", dash.devices_stations_partial, name="edge_devices_stations_partial"),
    path("devices/<uuid:device_id>/", dash.device_detail, name="edge_device_detail"),
    path("devices/<uuid:device_id>/update", dash.device_update, name="edge_device_update"),
    path("devices/<uuid:device_id>/action", dash.device_action, name="edge_device_action"),
    path("devices/<uuid:device_id>/reset", dash.device_reset, name="edge_device_reset"),
    path("devices/<uuid:device_id>/screenshot/capture", dash.device_screenshot_capture, name="edge_device_screenshot_capture"),
    path("devices/<uuid:device_id>/screenshot/latest", dash.device_screenshot_latest, name="edge_device_screenshot_latest"),
    path("devices/<uuid:device_id>/deactivate", dash.deactivate, name="edge_device_deactivate"),
    path("codes/create", dash.create_code, name="edge_create_code"),
    path("cloud/", dash.cloud_health, name="edge_cloud"),
    path("cloud/retry", dash.cloud_retry, name="edge_cloud_retry"),
    path("cloud/register", dash.cloud_register, name="edge_cloud_register"),
    path("cloud/sync-now", dash.cloud_sync_now, name="edge_cloud_sync_now"),
    path("cloud/test-connection", dash.cloud_test_connection, name="edge_cloud_test_connection"),
    path("cloud/reset", dash.cloud_reset, name="edge_cloud_reset"),
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
    path("api/v1/client/user-login", api.ClientUserLoginView.as_view(), name="api_client_user_login"),
    path("api/v1/client/user-logout", api.ClientUserLogoutView.as_view(), name="api_client_user_logout"),
    path("api/v1/client/change-password", api.ClientChangePasswordView.as_view(), name="api_client_change_password"),
    path("api/v1/client/admin-unlock", api.ClientAdminUnlockView.as_view(), name="api_client_admin_unlock"),
    path("api/v1/client/reset-pairing", api.ClientResetPairingView.as_view(), name="api_client_reset_pairing"),
    path("static/updates/<path:filename>", api.download_update_file, name="download_update_file"),
] + base_patterns()
