from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from apps.synchronization.cloud_client import CloudUnavailable
from apps.synchronization.events import emit
from apps.synchronization.models import EdgeIdentity, OutboxEvent, OutboxStatus
from apps.synchronization.outbox import (
    backoff_seconds,
    drain_outbox,
    pending_counts,
    retry_failed,
)


class FakeCloud:
    """Stands in for CloudClient.post_events in drain tests."""

    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {}
        self.error = error
        self.calls: list[list[dict]] = []

    def post_events(self, events: list[dict]) -> dict:
        self.calls.append(events)
        if self.error is not None:
            raise self.error
        return self.response


def _emit(note: str = "x") -> OutboxEvent:
    with transaction.atomic():
        return emit(
            "edge.test",
            aggregate_type="edge",
            aggregate_id="agg-1",
            payload={"note": note},
        )


@pytest.mark.django_db
def test_emit_allocates_monotonic_sequence(identity) -> None:
    first = _emit("one")
    second = _emit("two")
    assert (first.local_sequence, second.local_sequence) == (1, 2)
    assert first.edge_id == identity.edge_id
    assert first.schema_version == 1


@pytest.mark.django_db(transaction=True)
def test_emit_requires_business_transaction(identity) -> None:
    with pytest.raises(RuntimeError, match="same transaction"):
        emit("edge.test", aggregate_type="edge", aggregate_id="agg-1")


@pytest.mark.django_db
def test_emit_rejects_unknown_event_type(identity) -> None:
    with pytest.raises(ValueError, match="unknown event_type"):
        with transaction.atomic():
            emit("ledger.magically_changed", aggregate_type="edge", aggregate_id="agg-1")


@pytest.mark.django_db
def test_rolled_back_business_transaction_leaves_no_event(identity) -> None:
    class Rollback(Exception):
        pass

    with pytest.raises(Rollback):
        with transaction.atomic():
            emit("edge.test", aggregate_type="edge", aggregate_id="agg-1")
            raise Rollback

    assert OutboxEvent.objects.count() == 0
    assert EdgeIdentity.get_solo().next_sequence == 1


@pytest.mark.django_db
def test_drain_acknowledges_and_advances_watermark(identity) -> None:
    first = _emit("one")
    second = _emit("two")
    cloud = FakeCloud(
        {
            "accepted": [str(first.event_id), str(second.event_id)],
            "duplicates": [],
            "rejected": [],
            "watermark": 2,
        }
    )

    stats = drain_outbox(client=cloud)

    assert stats["sent"] == 2
    assert stats["accepted"] == 2
    assert stats["SYNCED"] == 2
    assert stats["PENDING"] == 0
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == OutboxStatus.SYNCED
    assert second.cloud_acknowledged_at is not None
    assert EdgeIdentity.get_solo().last_acked_sequence == 2
    # Second drain has nothing to send.
    assert drain_outbox(client=cloud)["sent"] == 0
    assert len(cloud.calls) == 1


@pytest.mark.django_db
def test_duplicate_acknowledgement_counts_as_success(identity) -> None:
    event = _emit("dup")
    cloud = FakeCloud({"accepted": [], "duplicates": [str(event.event_id)], "rejected": []})

    stats = drain_outbox(client=cloud)

    event.refresh_from_db()
    assert event.status == OutboxStatus.SYNCED
    assert stats["duplicates"] == 1


@pytest.mark.django_db
def test_unavailable_cloud_defers_with_backoff(identity) -> None:
    event = _emit("offline")
    cloud = FakeCloud(error=CloudUnavailable("connection refused"))

    stats = drain_outbox(client=cloud)
    event.refresh_from_db()

    assert stats["error"] == "connection refused"
    assert event.status == OutboxStatus.PENDING
    assert event.attempts == 1
    assert event.next_attempt_at > timezone.now()

    # Before the backoff expires, nothing is retried.
    early = FakeCloud({"accepted": [str(event.event_id)], "duplicates": [], "rejected": []})
    assert drain_outbox(client=early, now=timezone.now())["sent"] == 0
    assert early.calls == []

    # After it expires, the same event goes out and is acknowledged.
    later = FakeCloud({"accepted": [str(event.event_id)], "duplicates": [], "rejected": []})
    stats = drain_outbox(client=later, now=timezone.now() + timedelta(minutes=5))
    event.refresh_from_db()
    assert event.status == OutboxStatus.SYNCED
    assert stats["accepted"] == 1


@pytest.mark.django_db
def test_failed_event_blocks_later_events_until_retry(identity) -> None:
    first = _emit("one")
    second = _emit("two")
    OutboxEvent.objects.filter(pk=first.pk).update(
        status=OutboxStatus.FAILED, last_error="poison"
    )
    cloud = FakeCloud()

    stats = drain_outbox(client=cloud)

    assert stats["blocked"] is True
    assert cloud.calls == []
    assert OutboxEvent.objects.get(pk=second.pk).status == OutboxStatus.PENDING

    assert retry_failed(str(first.event_id)) == 1
    cloud.response = {
        "accepted": [str(first.event_id), str(second.event_id)],
        "duplicates": [],
        "rejected": [],
    }
    stats = drain_outbox(client=cloud)
    assert stats["SYNCED"] == 2
    assert EdgeIdentity.get_solo().last_acked_sequence == 2


@pytest.mark.django_db
def test_rejected_event_is_marked_failed(identity) -> None:
    event = _emit("bad")
    cloud = FakeCloud(
        {"accepted": [], "duplicates": [], "rejected": [{"event_id": str(event.event_id), "reason": "schema"}]}
    )

    stats = drain_outbox(client=cloud)
    event.refresh_from_db()

    assert event.status == OutboxStatus.FAILED
    assert event.last_error == "schema"
    assert stats["rejected"] == 1
    assert stats["blocked"] is True


@pytest.mark.django_db
def test_syncing_events_are_recovered_after_crash(identity) -> None:
    event = _emit("crash")
    OutboxEvent.objects.filter(pk=event.pk).update(status=OutboxStatus.SYNCING)

    cloud = FakeCloud({"accepted": [str(event.event_id)], "duplicates": [], "rejected": []})
    stats = drain_outbox(client=cloud)

    event.refresh_from_db()
    assert event.status == OutboxStatus.SYNCED
    assert stats["sent"] == 1


@pytest.mark.django_db
def test_pending_counts_reports_every_status(identity) -> None:
    _emit("one")
    counts = pending_counts()
    assert set(counts) == set(OutboxStatus.values)
    assert counts[OutboxStatus.PENDING] == 1


def test_backoff_is_exponential_and_capped() -> None:
    assert [backoff_seconds(n, jitter=False) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 8.0]
    assert backoff_seconds(50, jitter=False) == 60.0
