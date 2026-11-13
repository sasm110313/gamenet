from django.contrib import admin

from apps.clients.models import ClientDevice
from apps.commands.models import DeviceCommand, InboundRemoteCommand, RemoteCommand
from apps.devices.models import RegistrationCode
from apps.synchronization.models import (
    ConfigSnapshot,
    EdgeNode,
    EdgeRegistrationCode,
    OutboxEvent,
    SyncEvent,
)

admin.site.register(ClientDevice)
admin.site.register(RegistrationCode)
admin.site.register(EdgeNode)
admin.site.register(EdgeRegistrationCode)
admin.site.register(OutboxEvent)
admin.site.register(SyncEvent)
admin.site.register(ConfigSnapshot)
admin.site.register(RemoteCommand)
admin.site.register(InboundRemoteCommand)
admin.site.register(DeviceCommand)
