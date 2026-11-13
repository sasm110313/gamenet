import asyncio
import json
import queue
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from apps.core import rahro
from apps.customers.models import Customer
from apps.ingress.views import RahroCustomerSyncView
from apps.synchronization.cloud_client import CloudClient, CloudUnavailable
from apps.synchronization.edge_credentials import EdgeCredentials, load_credentials
from apps.synchronization.edge_ws import EdgeWebSocketClient
from apps.synchronization.events import emit
from apps.synchronization.ingest import ingest_batch
from apps.synchronization.models import EdgeIdentity, OutboxStatus, RahroDelivery, SyncEvent
from apps.synchronization.outbox import drain_outbox, retry_failed


def creds(url="http://cloud.test"):
    return EdgeCredentials(str(uuid4()), "test-secret", url, "")


@pytest.mark.parametrize("value", [[], None, "proxy page"])
def test_cloud_non_object_json_is_transient(value):
    client = CloudClient(creds())
    client.session = Mock()
    client.session.request.return_value = Mock(status_code=200, json=Mock(return_value=value))
    with pytest.raises(CloudUnavailable):
        client.fetch_config()


def test_cloud_invalid_json_is_transient():
    client = CloudClient(creds())
    client.session = Mock()
    client.session.request.return_value = Mock(status_code=200, json=Mock(side_effect=ValueError("bad JSON")))
    with pytest.raises(CloudUnavailable):
        client.heartbeat({})


@pytest.mark.django_db
def test_credentials_use_persisted_registration_url(identity):
    identity.cloud_base_url = "https://registered.example"
    identity.save()
    with patch("apps.synchronization.edge_credentials.store") as store:
        store.return_value.load.return_value = {"edge_id": str(identity.edge_id), "secret": "secret"}
        assert load_credentials().base_url == "https://registered.example"


def test_stopped_websocket_thread_can_be_joined():
    client = EdgeWebSocketClient(creds(), queue.Queue())
    client.stop()
    client.start()
    client.join(timeout=2)
    assert not client.is_alive()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_websocket_plain_http_and_async_database_catalog_updates(identity, monkeypatch):
    import websockets

    applied = asyncio.Event()
    loop = asyncio.get_running_loop()

    def save_catalog(catalog, *, version):
        assert EdgeIdentity.objects.count() == 1  # Fails if called in the asyncio thread.
        assert catalog == [{"id": "game"}] and version == 2
        loop.call_soon_threadsafe(applied.set)

    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "welcome"}))
        await ws.send(json.dumps({"type": "games_catalog_update", "games_catalog": [{"id": "game"}], "games_version": 2}))
        await ws.wait_closed()

    monkeypatch.setattr("apps.applications.services.save_games_catalog", save_catalog)
    monkeypatch.setattr("apps.synchronization.edge_ws.record_sync_log", lambda *a, **k: None)
    monkeypatch.setattr("apps.synchronization.daemon.trigger_sync_now", lambda: None)
    async with websockets.serve(server, "127.0.0.1", 0) as listener:
        port = listener.sockets[0].getsockname()[1]
        client = EdgeWebSocketClient(creds(f"http://127.0.0.1:{port}"), queue.Queue())
        task = asyncio.create_task(client._session())
        try:
            await asyncio.wait_for(applied.wait(), 5)
        finally:
            client.stop()
            with pytest.raises(asyncio.CancelledError):
                await task


def make_event():
    with transaction.atomic():
        return emit("edge.test", aggregate_type="edge", aggregate_id="test")


@pytest.mark.django_db
def test_outbox_active_claim_is_not_recovered_by_second_drain(identity):
    event = make_event()
    nested = Mock()
    nested.post_events.return_value = {"accepted": []}

    def post(_events):
        assert drain_outbox(client=nested)["sent"] == 0
        return {"accepted": [str(event.event_id)]}

    drain_outbox(client=SimpleNamespace(post_events=post))
    nested.post_events.assert_not_called()


@pytest.mark.django_db
def test_outbox_watermark_crosses_previously_synced_tail(identity):
    first, second = make_event(), make_event()
    cloud = Mock()
    cloud.post_events.return_value = {
        "accepted": [str(second.event_id)],
        "rejected": [{"event_id": str(first.event_id), "reason": "temporary projection defect"}],
    }
    drain_outbox(client=cloud)
    retry_failed(str(first.event_id))
    cloud.post_events.return_value = {"accepted": [str(first.event_id)]}
    drain_outbox(client=cloud)
    assert EdgeIdentity.get_solo().last_acked_sequence == second.local_sequence


@pytest.mark.django_db
def test_outbox_recovers_crash_between_status_and_watermark_update(identity):
    event = make_event()
    event.status = OutboxStatus.SYNCED
    event.save(update_fields=["status"])
    assert drain_outbox(client=Mock())["sent"] == 0
    assert EdgeIdentity.get_solo().last_acked_sequence == event.local_sequence


@pytest.mark.parametrize("response", [{}, {"accepted": "invalid"}, {"rejected": [None]}])
@pytest.mark.django_db
def test_partial_or_malformed_ack_is_retryable(identity, response):
    event = make_event()
    cloud = Mock()
    cloud.post_events.return_value = response
    drain_outbox(client=cloud)
    event.refresh_from_db()
    assert event.status == OutboxStatus.PENDING
    assert event.next_attempt_at is not None


@pytest.mark.django_db
def test_rejected_cloud_projection_retries_and_rolls_back_partial_writes(edge_node, settings):
    settings.GAMENET_ROLE = "cloud"
    raw = {
        "event_id": str(uuid4()), "local_sequence": 1, "event_type": "edge.test",
        "aggregate_type": "edge", "aggregate_id": "test", "schema_version": 1,
        "occurred_at": timezone.now().isoformat(), "payload": {},
    }

    def fail(record):
        Customer.objects.create(edge_id=edge_node.id, full_name="must roll back")
        raise RuntimeError("projection failed")

    with patch("apps.synchronization.ingest.apply_event", side_effect=fail):
        assert ingest_batch(edge_node, [raw])["rejected"]
    assert not Customer.objects.filter(full_name="must roll back").exists()
    with patch("apps.synchronization.ingest.apply_event") as apply:
        result = ingest_batch(edge_node, [raw])
        apply.assert_called_once()
    assert result["accepted"] == [raw["event_id"]]
    assert result["duplicates"] == []
    assert SyncEvent.objects.get(event_id=raw["event_id"]).status == "APPLIED"


@pytest.mark.django_db
def test_rahro_delivery_is_durable_deduplicated_and_retried(monkeypatch):
    payload = {"session_id": str(uuid4()), "phone": "09120000000", "coupon_hours_used": 1}
    first = rahro.queue_session_record(payload)
    assert str(rahro.queue_session_record(payload).pk) == str(first.pk)
    send = Mock(side_effect=[False, True])
    monkeypatch.setattr(rahro, "record_session", send)
    assert rahro.drain_session_records() == 0
    first.refresh_from_db()
    assert first.delivered_at is None and first.attempts == 1
    assert rahro.drain_session_records(now=first.next_attempt_at) == 1
    first.refresh_from_db()
    assert first.delivered_at is not None
    assert first.attempts == 2
    assert rahro.drain_session_records(now=first.next_attempt_at + timedelta(hours=1)) == 0
    assert send.call_count == 2


@pytest.mark.parametrize("data", [None, [], {"success": False}, {"ok": False}, {"error": "refused"}])
def test_rahro_http_200_is_not_enough_to_confirm_record(data):
    with patch.object(rahro, "_run", return_value={"status": 200, "data": data}):
        assert rahro.record_session({"session_id": str(uuid4())}) is False


def test_discount_rejects_invalid_response_and_invalidates_success_cache():
    with patch.object(rahro, "_run", return_value={"status": 200, "data": []}):
        assert rahro.apply_discount(phone="0912", username="1234", discount_percent=50)[0] is False
    cache.set("rahro_status_0912_1234", {"found": True, "total_coupons": 1})
    with patch.object(rahro, "_run", return_value={"status": 200, "data": {"success": True}}):
        assert rahro.apply_discount(phone="0912", username="1234", discount_percent=50)[0]
    assert cache.get("rahro_status_0912_1234") is None


def sync_customer(data):
    request = APIRequestFactory().post("/api/rahro/sync", data, format="json", HTTP_X_INTERNAL_SECRET="test-secret")
    return RahroCustomerSyncView.as_view()(request)


@pytest.mark.django_db
def test_rahro_webhook_queues_without_browser_messages_and_preserves_omitted_coupons(edge_node, settings):
    from apps.commands.models import RemoteCommand

    settings.GAMENET_ROLE = "cloud"
    settings.RAHRO_GAMENET_SHARED_SECRET = "test-secret"
    identity = Customer()
    identity.set_password("external-password")
    payload = {"phone": "09123334444", "full_name": "Rahro user", "login_code": "1234", "active_coupons": 3, "password_hash": identity.password_hash}
    assert sync_customer(payload).status_code == 200
    command = RemoteCommand.objects.get(edge=edge_node)
    assert command.payload["password_hash"] == identity.password_hash
    assert command.payload["active_coupons"] == 3
    payload.pop("active_coupons")
    assert sync_customer(payload).status_code == 200
    assert Customer.objects.get(phone=payload["phone"]).active_coupons == 3
    assert RemoteCommand.objects.filter(edge=edge_node).count() == 2
    assert "active_coupons" not in RemoteCommand.objects.filter(edge=edge_node).latest("issued_at").payload
    payload.update(active_coupons=0, coupon_hours=9)
    assert sync_customer(payload).status_code == 200
    assert Customer.objects.get(phone=payload["phone"]).active_coupons == 0


@pytest.mark.django_db
def test_rahro_parent_exclusion_no_longer_raises_import_or_field_errors(edge_node, settings):
    settings.GAMENET_ROLE = "cloud"
    settings.RAHRO_GAMENET_SHARED_SECRET = "test-secret"
    customer = Customer.objects.create(edge_id=edge_node.id, full_name="Parent", phone="09123334444")
    assert sync_customer({"phone": customer.phone, "role": "PARENT"}).status_code == 200
    assert not Customer.objects.filter(pk=customer.pk).exists()


@pytest.mark.django_db
def test_rahro_webhook_queue_failure_rolls_back_instead_of_claiming_success(edge_node, settings):
    settings.GAMENET_ROLE = "cloud"
    settings.RAHRO_GAMENET_SHARED_SECRET = "test-secret"
    with patch("apps.synchronization.command_service.issue_command", side_effect=RuntimeError("queue failed")):
        with pytest.raises(RuntimeError, match="queue failed"):
            sync_customer({"phone": "09123334444", "full_name": "must roll back"})
    assert not Customer.objects.filter(phone="09123334444").exists()


@pytest.mark.django_db
def test_imported_password_reaches_edge_customer(customer):
    from apps.synchronization.command_service import _dispatch

    external = Customer()
    external.set_password("new-external-password")
    _dispatch("catalog.customer.upsert", {
        "customer_id": str(customer.pk), "base_revision": customer.revision,
        "full_name": customer.full_name, "phone": customer.phone, "password_hash": external.password_hash,
    }, origin="test")
    customer.refresh_from_db()
    assert customer.check_password("new-external-password")


@pytest.mark.django_db
def test_session_commit_persists_one_rahro_record_and_syncs_coupon_consumption(customer, device):
    from apps.clients.models import ClientStatus
    from apps.devices.services import set_status
    from apps.sessions.models import GamingSession
    from apps.sessions.services import start_session, stop_session
    from apps.synchronization.handlers import session_ended
    from apps.synchronization.models import OutboxEvent
    from apps.wallets.models import Wallet

    customer.group.name = "لیگ رهرو"
    customer.group.save()
    customer.active_coupons = 1
    customer.save()
    Wallet.objects.filter(customer=customer).update(balance=100000)
    set_status(device, ClientStatus.ONLINE, force=True)
    session = start_session(customer, device)
    GamingSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=30))
    ended, _ = stop_session(session)
    record = RahroDelivery.objects.get(pk=session.pk)
    assert record.payload["coupons_used"] == 1
    assert record.payload["coupon_hours_used"] == 1
    assert record.delivered_at is None
    assert OutboxEvent.objects.get(event_type="customer.updated").payload["active_coupons"] == 0
    event = OutboxEvent.objects.get(event_type="session.ended")
    assert event.payload["rahro_delivery_owner"] == "edge"
    with patch.object(rahro, "queue_session_record") as enqueue:
        session_ended(SimpleNamespace(payload=event.payload, edge_id=session.edge_id, occurred_at=timezone.now()))
        enqueue.assert_not_called()
    stop_session(ended)
    assert RahroDelivery.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_writer_failure_ends_websocket_session(monkeypatch):
    ready = asyncio.Event()

    class Socket:
        first = True

        async def send(self, message):
            if json.loads(message).get("type") != "hello":
                raise RuntimeError("writer failed")

        async def recv(self):
            if self.first:
                self.first = False
                return '{"type":"welcome"}'
            ready.set()
            return await asyncio.Future()

    class Context:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("apps.synchronization.edge_ws.websockets.connect", lambda *a, **k: Context())
    monkeypatch.setattr("apps.synchronization.edge_ws.record_sync_log", lambda *a, **k: None)
    monkeypatch.setattr("apps.synchronization.outbox.unblock_for_reconnect", lambda: 0)
    monkeypatch.setattr("apps.synchronization.daemon.trigger_sync_now", lambda: None)
    client = EdgeWebSocketClient(creds(), queue.Queue())
    task = asyncio.create_task(client._session())
    await asyncio.wait_for(ready.wait(), 2)
    assert client.enqueue_outbound({"type": "test"})
    with pytest.raises(RuntimeError, match="writer failed"):
        await asyncio.wait_for(task, 2)


@pytest.mark.django_db
def test_worker_once_constructs_and_closes_its_own_cloud_client(identity):
    from apps.synchronization.edge_runtime import run_once

    client = Mock()
    client.fetch_commands.return_value = {"commands": []}
    client.post_events.return_value = {}
    client.heartbeat.return_value = {}
    client.base = "https://cloud.example"
    with patch("apps.synchronization.edge_runtime.load_credentials", return_value=creds()), \
         patch("apps.synchronization.edge_runtime.CloudClient", return_value=client), \
         patch("apps.synchronization.edge_runtime.sync_config", return_value={}), \
         patch("apps.synchronization.edge_runtime.sync_seed_catalog_if_empty", return_value=0), \
         patch("apps.devices.services.mark_stale_devices_offline", return_value=0):
        run_once()
    client.close.assert_called_once()
    client.heartbeat.assert_called_once()


@pytest.mark.parametrize("extra", [
    {"active_coupons": -1}, {"active_coupons": 1.5}, {"is_deleted": "false"}, {"hourly_rate": "invalid"},
])
@pytest.mark.django_db
def test_invalid_rahro_input_returns_400_not_a_mutation(edge_node, settings, extra):
    settings.GAMENET_ROLE = "cloud"
    settings.RAHRO_GAMENET_SHARED_SECRET = "test-secret"
    assert sync_customer({"phone": "09123334444", **extra}).status_code == 400
    assert not Customer.objects.filter(phone="09123334444").exists()
