from __future__ import annotations

from django.urls import path

from apps.accounts import views as account_views
from apps.ingress import dashboard as dash
from apps.ingress import management
from apps.ingress import views as api
from apps.reports import dashboard as reports
from apps.applications import views as app_views
from apps.core import views_announcements as ann_views
from apps.devices.views import download_update_file
from gamenet.urls_common import base_patterns

urlpatterns = [
    path("", dash.overview, name="cloud_overview"),
    path("account/", account_views.account_settings, name="cloud_account"),
    path("announcements/", ann_views.announcements_list, name="cloud_announcements"),
    path("api/v1/announcements/", ann_views.api_announcements, name="api_announcements_cloud"),
    path("games/", app_views.games_list, name="cloud_games"),
    path("api/v1/games/", app_views.api_games_catalog, name="api_games_catalog_cloud"),
    path("customers/", management.customers, name="cloud_customers"),
    path("customers/create", management.customer_create, name="cloud_customer_create"),
    path("customers/create/", management.customer_create),
    path("customers/<uuid:customer_id>/", management.customer_detail, name="cloud_customer_detail"),
    path(
        "customers/<uuid:customer_id>/rahro-discount",
        management.customer_rahro_discount,
        name="cloud_customer_rahro_discount",
    ),
    path(
        "customers/<uuid:customer_id>/recharge",
        management.customer_rahro_recharge,
        name="cloud_customer_rahro_recharge",
    ),
    path(
        "customers/<uuid:customer_id>/settle-debt",
        management.customer_settle_debt,
        name="cloud_customer_settle_debt",
    ),
    path("sessions/", reports.sessions, name="cloud_sessions"),
    path("ledger/", reports.ledger, name="cloud_ledger"),
    path("pricing/", management.pricing, name="cloud_pricing"),
    path("manage/pricing/", management.pricing_redirect, name="cloud_manage_pricing"),
    path("manage/pricing/tariffs/create", management.tariff_create, name="cloud_manage_tariff_create"),
    path(
        "manage/pricing/tariffs/<uuid:tariff_id>/update",
        management.tariff_update,
        name="cloud_manage_tariff_update",
    ),
    path("manage/pricing/groups/create", management.group_create, name="cloud_manage_group_create"),
    path(
        "manage/pricing/groups/<uuid:group_id>/update",
        management.group_update,
        name="cloud_manage_group_update",
    ),
    path("manage/customers/", management.customers_redirect, name="cloud_manage_customers"),
    path("manage/customers/create", management.customer_create, name="cloud_manage_customer_create"),
    path("manage/customers/create/", management.customer_create),
    path(
        "manage/customers/<uuid:customer_id>/",
        management.customer_detail_redirect,
        name="cloud_manage_customer",
    ),
    path(
        "manage/customers/<uuid:customer_id>/update",
        management.customer_update,
        name="cloud_manage_customer_update",
    ),
    path(
        "manage/customers/<uuid:customer_id>/rahro-discount",
        management.customer_rahro_discount,
        name="cloud_manage_customer_rahro_discount",
    ),
    path(
        "manage/customers/<uuid:customer_id>/recharge",
        management.customer_rahro_recharge,
        name="cloud_manage_customer_rahro_recharge",
    ),
    path(
        "manage/customers/<uuid:customer_id>/wallet",
        management.wallet,
        name="cloud_manage_wallet",
    ),
    path(
        "manage/customers/<uuid:customer_id>/rates/create",
        management.customer_rate_create,
        name="cloud_manage_rate_create",
    ),
    path(
        "manage/customers/<uuid:customer_id>/rates/<uuid:rate_id>/update",
        management.customer_rate_update,
        name="cloud_manage_rate_update",
    ),
    path(
        "manage/customers/<uuid:customer_id>/rates/<uuid:rate_id>/deactivate",
        management.customer_rate_deactivate,
        name="cloud_manage_rate_deactivate",
    ),
    path(
        "manage/customers/<uuid:customer_id>/session/start",
        management.session_start,
        name="cloud_manage_session_start",
    ),
    path(
        "manage/sessions/<uuid:session_id>/stop",
        management.session_stop,
        name="cloud_manage_session_stop",
    ),
    path("devices/", dash.devices, name="cloud_devices"),
    path("devices/grid", dash.device_grid, name="cloud_device_grid"),
    path("devices/create-code", dash.create_client_code, name="cloud_create_client_code"),
    path("devices/<uuid:device_id>/", dash.device_detail, name="cloud_device_detail"),
    path("devices/<uuid:device_id>/update", dash.device_update, name="cloud_device_update"),
    path("devices/<uuid:device_id>/action", dash.device_action, name="cloud_device_action"),
    path("devices/<uuid:device_id>/start-session", dash.device_start_session, name="cloud_device_start_session"),
    path("devices/<uuid:device_id>/screenshot/capture", dash.device_screenshot_capture, name="cloud_device_screenshot_capture"),
    path("devices/<uuid:device_id>/screenshot/latest", dash.device_screenshot_latest, name="cloud_device_screenshot_latest"),
    path("edges/", dash.edges, name="cloud_edges"),
    path("edges/create-code", dash.create_code, name="cloud_create_code"),
    path("edges/<uuid:edge_id>/", dash.edge_detail, name="cloud_edge_detail"),
    path("edges/<uuid:edge_id>/action", dash.edge_action, name="cloud_edge_action"),
    path("edges/<uuid:edge_id>/revoke", dash.edge_revoke, name="cloud_edge_revoke"),
    path("devices/<uuid:device_id>/action", dash.device_action, name="cloud_device_action"),
    path("commands/", dash.commands, name="cloud_commands"),
    path("events/", dash.events, name="cloud_events"),
    path("config/", dash.config, name="cloud_config"),
    # edge-facing API
    path("api/v1/edge/register", api.EdgeRegisterView.as_view(), name="api_edge_register"),
    path("api/v1/edge/events:batch", api.EdgeEventsView.as_view(), name="api_edge_events"),
    path("api/v1/edge/heartbeat", api.EdgeHeartbeatView.as_view(), name="api_edge_heartbeat"),
    path("api/v1/edge/commands/pending", api.EdgeCommandsPendingView.as_view(), name="api_edge_commands"),
    path("api/v1/edge/config", api.EdgeConfigView.as_view(), name="api_edge_config"),
    path("api/v1/edge/seed-catalog", api.EdgeSeedCatalogView.as_view(), name="api_edge_seed_catalog"),
    # integration API (Rahro <-> GameNet)
    path("api/v1/integration/sync-customer/", api.RahroCustomerSyncView.as_view(), name="api_rahro_customer_sync"),
    path("api/v1/integration/record-paid-session/", api.RahroRecordPaidSessionView.as_view(), name="api_rahro_record_paid_session"),
    path("static/updates/<path:filename>", download_update_file, name="cloud_download_update_file"),
] + base_patterns()
