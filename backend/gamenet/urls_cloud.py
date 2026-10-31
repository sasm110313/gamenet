from __future__ import annotations

from django.urls import path

from apps.ingress import dashboard as dash
from apps.ingress import views as api
from gamenet.urls_common import base_patterns

urlpatterns = [
    path("", dash.overview, name="cloud_overview"),
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
