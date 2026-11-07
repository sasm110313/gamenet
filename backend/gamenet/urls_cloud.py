from __future__ import annotations

from django.urls import path

from apps.ingress import dashboard as dash
from apps.ingress import management
from apps.ingress import views as api
from apps.reports import dashboard as reports
from gamenet.urls_common import base_patterns

urlpatterns = [
    path("", dash.overview, name="cloud_overview"),
    path("customers/", reports.customers, name="cloud_customers"),
    path("customers/<uuid:customer_id>/", reports.customer_detail, name="cloud_customer_detail"),
    path("sessions/", reports.sessions, name="cloud_sessions"),
    path("ledger/", reports.ledger, name="cloud_ledger"),
    path("pricing/", reports.pricing, name="cloud_pricing"),
    path("manage/pricing/", management.pricing, name="cloud_manage_pricing"),
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
    path("manage/customers/", management.customers, name="cloud_manage_customers"),
    path("manage/customers/create", management.customer_create, name="cloud_manage_customer_create"),
    path(
        "manage/customers/<uuid:customer_id>/",
        management.customer_detail,
        name="cloud_manage_customer",
    ),
    path(
        "manage/customers/<uuid:customer_id>/update",
        management.customer_update,
        name="cloud_manage_customer_update",
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
    path("edges/", dash.edges, name="cloud_edges"),
    path("edges/create-code", dash.create_code, name="cloud_create_code"),
    path("edges/<uuid:edge_id>/", dash.edge_detail, name="cloud_edge_detail"),
    path("edges/<uuid:edge_id>/action", dash.edge_action, name="cloud_edge_action"),
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
] + base_patterns()
