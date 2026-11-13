from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class ClientStatus(models.TextChoices):
    OFFLINE = "OFFLINE", "Offline"
    ONLINE = "ONLINE", "Online"
    LOCKED = "LOCKED", "Locked"
    IDLE = "IDLE", "Idle"
    STARTING = "STARTING", "Starting"
    ACTIVE = "ACTIVE", "Active"
    STOPPING = "STOPPING", "Stopping"
    ERROR = "ERROR", "Error"
    MAINTENANCE = "MAINTENANCE", "Maintenance"


class ConnectionStatus(models.TextChoices):
    ONLINE = "ONLINE", "Online"
    OFFLINE = "OFFLINE", "Offline"


class PowerStatus(models.TextChoices):
    ON = "ON", "On"
    OFF = "OFF", "Off"
    UNKNOWN = "UNKNOWN", "Unknown"


class KioskStatus(models.TextChoices):
    LOCKED = "LOCKED", "Locked"
    UNLOCKED = "UNLOCKED", "Unlocked"
    DISABLED = "DISABLED", "Disabled"


class OccupancyStatus(models.TextChoices):
    FREE = "FREE", "Free"
    BUSY = "BUSY", "Busy"
    MAINTENANCE = "MAINTENANCE", "Maintenance"


class HealthStatus(models.TextChoices):
    HEALTHY = "HEALTHY", "Healthy"
    ERROR = "ERROR", "Error"


# Transitions the hub accepts from a client's own reports. The hub may always
# force MAINTENANCE/OFFLINE (network truth), and admin commands may force LOCKED.
CLIENT_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ClientStatus.OFFLINE: {ClientStatus.ONLINE, ClientStatus.LOCKED},
    ClientStatus.ONLINE: {ClientStatus.LOCKED, ClientStatus.IDLE, ClientStatus.OFFLINE,
                          ClientStatus.MAINTENANCE, ClientStatus.STARTING},
    ClientStatus.IDLE: {ClientStatus.LOCKED, ClientStatus.ACTIVE, ClientStatus.OFFLINE,
                        ClientStatus.MAINTENANCE},
    ClientStatus.LOCKED: {ClientStatus.IDLE, ClientStatus.STARTING, ClientStatus.OFFLINE,
                          ClientStatus.MAINTENANCE},
    ClientStatus.STARTING: {ClientStatus.ACTIVE, ClientStatus.LOCKED, ClientStatus.ERROR},
    ClientStatus.ACTIVE: {ClientStatus.STOPPING, ClientStatus.ERROR, ClientStatus.OFFLINE,
                          ClientStatus.MAINTENANCE},
    ClientStatus.STOPPING: {ClientStatus.LOCKED, ClientStatus.ERROR},
    ClientStatus.ERROR: {ClientStatus.LOCKED, ClientStatus.IDLE, ClientStatus.MAINTENANCE},
    ClientStatus.MAINTENANCE: {ClientStatus.LOCKED, ClientStatus.IDLE, ClientStatus.OFFLINE},
}


class ClientDevice(models.Model):
    """A managed gaming PC.

    The `id` is the device identity used on the wire (`device_id`); the spec's
    `device_uuid` is this primary key. Edge rows are authoritative; cloud rows are
    read-only replicas written exclusively by the ingest service (`is_replica`).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=80)
    hostname = models.CharField(max_length=120, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    operating_system = models.CharField(max_length=120, blank=True)
    application_version = models.CharField(max_length=40, blank=True)
    status = models.CharField(
        max_length=16, choices=ClientStatus.choices, default=ClientStatus.OFFLINE, db_index=True
    )
    connection_status = models.CharField(
        max_length=16,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.OFFLINE,
        db_index=True,
    )
    power_status = models.CharField(
        max_length=16,
        choices=PowerStatus.choices,
        default=PowerStatus.UNKNOWN,
        db_index=True,
    )
    kiosk_status = models.CharField(
        max_length=16,
        choices=KioskStatus.choices,
        default=KioskStatus.LOCKED,
        db_index=True,
    )
    occupancy_status = models.CharField(
        max_length=16,
        choices=OccupancyStatus.choices,
        default=OccupancyStatus.FREE,
        db_index=True,
    )
    health_status = models.CharField(
        max_length=16,
        choices=HealthStatus.choices,
        default=HealthStatus.HEALTHY,
        db_index=True,
    )
    health_message = models.CharField(max_length=255, blank=True)
    last_power_change_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    connection_owner = models.CharField(max_length=100, blank=True, default="")
    registered_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    # SHA-256 of the device token; the token itself is never stored.
    token_hash = models.CharField(max_length=64, blank=True)
    token_issued_at = models.DateTimeField(null=True, blank=True)
    is_replica = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ClientStatus.values),
                name="clients_device_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(connection_status__in=ConnectionStatus.values),
                name="clients_device_connection_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(power_status__in=PowerStatus.values),
                name="clients_device_power_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(kiosk_status__in=KioskStatus.values),
                name="clients_device_kiosk_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(occupancy_status__in=OccupancyStatus.values),
                name="clients_device_occupancy_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(health_status__in=HealthStatus.values),
                name="clients_device_health_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["edge_id", "status"]),
            models.Index(fields=["edge_id", "connection_status", "occupancy_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.connection_status}/{self.occupancy_status})"

    @property
    def is_online(self) -> bool:
        return self.connection_status == ConnectionStatus.ONLINE

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in CLIENT_ALLOWED_TRANSITIONS.get(self.status, set())
