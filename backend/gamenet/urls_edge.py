from __future__ import annotations

from django.urls import path

from apps.devices import dashboard as dash
from apps.devices import views as api
from gamenet.urls_common import base_patterns

urlpatterns = [
    path("", dash.overview, name="edge_overview"),
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
