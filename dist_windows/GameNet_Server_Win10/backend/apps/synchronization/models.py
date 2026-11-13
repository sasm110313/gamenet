from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7


class EdgeStatus(models.TextChoices):
    REGISTERED = "REGISTERED", "Registered"
    ONLINE = "ONLINE", "Online"
    OFFLINE = "OFFLINE", "Offline"
    REVOKED = "REVOKED", "Revoked"


class OutboxStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SYNCING = "SYNCING", "Syncing"
    SYNCED = "SYNCED", "Synced"
    FAILED = "FAILED", "Failed"


class SyncEventStatus(models.TextChoices):
    APPLIED = "APPLIED", "Applied"
    REJECTED = "REJECTED", "Rejected"


class EdgeNode(models.Model):
    """Cloud-side registry of an edge install. `id` is the edge_uuid on the wire."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    name = models.CharField(max_length=120)
    site_name = models.CharField(max_length=160, blank=True)
    secret_hash = models.CharField(max_length=128)
    command_public_key = models.TextField()
    # Ed25519 private key, encrypted at rest (see apps.synchronization.crypto).
    command_private_key_enc = models.TextField()
    status = models.CharField(
        max_length=16, choices=EdgeStatus.choices, default=EdgeStatus.REGISTERED, db_index=True
    )
    software_version = models.CharField(max_length=40, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_acked_sequence = models.BigIntegerField(default=0)
    config_version = models.IntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} [{self.status}]"


class EdgeRegistrationCode(models.Model):
    """One-time code created by the cloud admin to bind a physical site."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    code = models.CharField(max_length=32, unique=True)
    note = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.OneToOneField(
        EdgeNode, null=True, blank=True, on_delete=models.SET_NULL, related_name="registration_code"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"code {self.code} ({'used' if self.used_at else 'open'})"


class EdgeIdentity(models.Model):
    """The edge's own identity. Singleton row (pk=1)."""

    id = models.BigAutoField(primary_key=True)
    edge_id = models.UUIDField(unique=True)
    name = models.CharField(max_length=120)
    cloud_base_url = models.URLField()
    credential_reference = models.CharField(max_length=255)
    command_public_key = models.TextField()
    status = models.CharField(
        max_length=16, choices=EdgeStatus.choices, default=EdgeStatus.REGISTERED
    )
    software_version = models.CharField(max_length=40, blank=True)
    last_connected_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_acked_sequence = models.BigIntegerField(default=0)
    next_sequence = models.BigIntegerField(default=1)
    config_version = models.IntegerField(default=0)
    last_config_check_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_solo(cls) -> "EdgeIdentity":
        obj = cls.objects.filter(pk=1).first()
        if obj is None:
            raise cls.DoesNotExist("edge is not registered with the cloud")
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"edge {self.edge_id}"


class OutboxEvent(models.Model):
    """Durable edge -> cloud event. Inserted in the same transaction as the fact."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    event_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    edge_id = models.UUIDField(db_index=True)
    local_sequence = models.BigIntegerField(unique=True)
    event_type = models.CharField(max_length=80, db_index=True)
    aggregate_type = models.CharField(max_length=60)
    aggregate_id = models.CharField(max_length=64)
    schema_version = models.IntegerField(default=settings.SYNC_SCHEMA_VERSION)
    occurred_at = models.DateTimeField(default=timezone.now)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12, choices=OutboxStatus.choices, default=OutboxStatus.PENDING
    )
    attempts = models.IntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    cloud_acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["local_sequence"]
        indexes = [
            models.Index(fields=["status", "local_sequence"]),
            models.Index(fields=["aggregate_type", "aggregate_id", "local_sequence"]),
        ]

    def __str__(self) -> str:
        return f"#{self.local_sequence} {self.event_type} [{self.status}]"


class SyncEvent(models.Model):
    """Cloud-side record of a received edge event (the replicated fact log)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    edge = models.ForeignKey(EdgeNode, on_delete=models.PROTECT, related_name="events")
    event_id = models.UUIDField()
    local_sequence = models.BigIntegerField()
    event_type = models.CharField(max_length=80)
    aggregate_type = models.CharField(max_length=60)
    aggregate_id = models.CharField(max_length=64)
    schema_version = models.IntegerField(default=settings.SYNC_SCHEMA_VERSION)
    occurred_at = models.DateTimeField()
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12, choices=SyncEventStatus.choices, default=SyncEventStatus.APPLIED
    )
    reject_reason = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["local_sequence"]
        constraints = [
            models.UniqueConstraint(fields=["edge", "event_id"], name="sync_unique_event_per_edge"),
        ]
        indexes = [
            models.Index(fields=["edge", "local_sequence"]),
            models.Index(fields=["aggregate_type", "aggregate_id", "local_sequence"]),
        ]

    def __str__(self) -> str:
        return f"sync {self.event_id} #{self.local_sequence} [{self.status}]"


class ConfigSnapshot(models.Model):
    """Versioned configuration distributed from cloud to edges."""

    id = models.BigAutoField(primary_key=True)
    version = models.IntegerField(unique=True)
    payload = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"config v{self.version}"


class AppliedConfig(models.Model):
    """Edge-side record of the config snapshot currently in force."""

    id = models.BigAutoField(primary_key=True)
    version = models.IntegerField(unique=True)
    content_hash = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"applied config v{self.version}"
