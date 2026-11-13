from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class CommandStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired"


class RemoteCommand(models.Model):
    """Cloud-issued command targeting an edge. Signed with the edge's public key
    counterpart; the edge executes it at most once."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge = models.ForeignKey("synchronization.EdgeNode", on_delete=models.CASCADE, related_name="commands")
    command_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=CommandStatus.choices, default=CommandStatus.PENDING, db_index=True
    )
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    signature = models.TextField()
    nonce = models.CharField(max_length=64, unique=True)
    # Cloud UI idempotency key: a double-click reuses the same command instead
    # of issuing a second financial operation.
    request_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["edge", "request_id"],
                condition=models.Q(request_id__isnull=False),
                name="commands_unique_request_per_edge",
            )
        ]

    def __str__(self) -> str:
        return f"{self.command_type} -> {self.edge.name} [{self.status}]"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    def envelope(self) -> dict:
        """Exactly the fields the edge verifies. Keep in sync with edge verify."""
        return {
            "command_id": str(self.id),
            "edge_id": str(self.edge_id),
            "command_type": self.command_type,
            "payload": self.payload,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "nonce": self.nonce,
        }


class InboundCommandStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    EXECUTING = "EXECUTING", "Executing"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired"


class InboundRemoteCommand(models.Model):
    """Edge-side ledger of remote commands. The unique command_id is the
    exactly-once guard: a replay finds the existing row and never re-executes."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    command_id = models.UUIDField(unique=True)
    edge_id = models.UUIDField()
    command_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    signature = models.TextField()
    status = models.CharField(
        max_length=12, choices=InboundCommandStatus.choices, default=InboundCommandStatus.RECEIVED
    )
    received_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    reject_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"inbound {self.command_type} [{self.status}]"


class DeviceCommandStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    FAILED = "FAILED", "Failed"
    EXPIRED = "EXPIRED", "Expired"


class DeviceCommand(models.Model):
    """Edge -> Windows client command. `command_id` is chosen by the edge and
    echoed by the client, so retries are safe."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    client = models.ForeignKey("clients.ClientDevice", on_delete=models.CASCADE, related_name="commands")
    command_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=DeviceCommandStatus.choices, default=DeviceCommandStatus.PENDING, db_index=True
    )
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    origin_remote_command_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self) -> str:
        return f"{self.command_type} -> {self.client.name} [{self.status}]"
