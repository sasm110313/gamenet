from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from apps.clients.models import ClientDevice, ClientStatus, ConnectionStatus
from apps.devices.consumers import DeviceConsumer
from apps.devices.services import mark_stale_devices_offline, set_status
from apps.devices.views import ClientUserLoginView, ClientUserLogoutView
from apps.sessions.models import BillingMode, DisconnectPolicy, GamingSession, SessionStatus
from apps.sessions.services import (
    enforce_active_session_policies, reconcile_orphaned_sessions, start_session, stop_session,
)
from apps.wallets.models import Wallet
from apps.wallets.services import settle_debt

pytestmark = pytest.mark.django_db


@pytest.fixture
def funded(customer, device, monkeypatch):
    monkeypatch.setattr("apps.sessions.services._send_rahro_record", lambda payload: None)
    Wallet.objects.filter(customer=customer).update(balance=100_000)
    set_status(device, ClientStatus.ONLINE, force=True)
    return customer, device


def consumer_for(device, owner="new"):
    consumer = DeviceConsumer()
    consumer.device = device
    consumer.channel_name = owner
    consumer.scope = {}
    consumer._shutdown_reported = False
    return consumer


@pytest.mark.parametrize("policy", DisconnectPolicy.values)
def test_disconnect_honors_policy_and_grace(funded, policy):
    customer, device = funded
    session = start_session(customer, device, disconnect_policy=policy)
    now = timezone.now()
    set_status(device, ClientStatus.OFFLINE, force=True)
    enforce_active_session_policies(now + timedelta(seconds=30))
    session.refresh_from_db()
    assert session.status == SessionStatus.ACTIVE
    assert (session.paused_at is not None) == (policy == DisconnectPolicy.PAUSE)
    enforce_active_session_policies(now + timedelta(seconds=100))
    session.refresh_from_db()
    assert (session.status == SessionStatus.COMPLETED) == (policy == DisconnectPolicy.AUTO_STOP)


def test_old_connection_cannot_disconnect_new_owner(funded):
    customer, device = funded
    session = start_session(customer, device)
    ClientDevice.objects.filter(pk=device.pk).update(connection_owner="new")
    consumer_for(device, "old")._disconnect_if_owner(1000)
    device.refresh_from_db()
    session.refresh_from_db()
    assert device.connection_status == ConnectionStatus.ONLINE
    assert session.status == SessionStatus.ACTIVE
    consumer_for(device)._disconnect_if_owner(1000)
    device.refresh_from_db()
    assert device.connection_status == ConnectionStatus.OFFLINE
    assert device.connection_owner == ""


def test_combined_exposure_stops_all_sessions_without_negative_wallet(funded):
    customer, device = funded
    other = ClientDevice.objects.create(edge_id=device.edge_id, name="PC-02", status=ClientStatus.ONLINE)
    first = start_session(customer, device)
    second = start_session(customer, other)
    now = timezone.now()
    GamingSession.objects.filter(pk__in=[first.pk, second.pk]).update(
        started_at=now - timedelta(minutes=90),
    )
    assert enforce_active_session_policies(now) == 2
    assert not GamingSession.objects.filter(status=SessionStatus.ACTIVE).exists()
    assert Wallet.objects.get(customer=customer).balance >= 0
    assert sum(GamingSession.objects.values_list("cost", flat=True)) <= 100_000


def test_coupon_is_reserved_and_timed_quote_uses_discount(funded):
    customer, device = funded
    customer.active_coupons = 1
    customer.group.name = "لیگ"
    customer.group.save()
    customer.save()
    Wallet.objects.filter(customer=customer).update(balance=30_000)
    first = start_session(customer, device, billing_mode=BillingMode.TIMED, planned_duration_minutes=60)
    assert first.coupon_hours == 1
    assert first.estimated_cost == 20_000
    other = ClientDevice.objects.create(edge_id=device.edge_id, name="PC-02", status=ClientStatus.ONLINE)
    Wallet.objects.filter(customer=customer).update(balance=100_000)
    second = start_session(customer, other)
    assert second.coupon_hours == 0


@pytest.mark.parametrize("paused", [False, True])
def test_timed_settlement_caps_elapsed_and_charge(funded, paused):
    customer, device = funded
    session = start_session(customer, device, billing_mode=BillingMode.TIMED, planned_duration_minutes=60)
    now = timezone.now()
    GamingSession.objects.filter(pk=session.pk).update(
        started_at=now - timedelta(minutes=75), paused_seconds=600 if paused else 0,
    )
    ended, entry = stop_session(session, at=now)
    assert ended.elapsed_seconds == 3600
    assert ended.cost == 40_000
    assert entry.amount == -40_000


def test_debt_payment_retries_return_same_entry(funded):
    customer, _ = funded
    customer.debt_balance = 50_000
    customer.save()
    command_id, entry_id = uuid4(), uuid4()
    args = dict(source_command_id=command_id, entry_id=entry_id, tracking_code="PAY-TEST")
    paid, entry = settle_debt(customer, 20_000, **args)
    again, same = settle_debt(customer, 20_000, **args)
    customer.refresh_from_db()
    assert paid == again == 20_000
    assert entry.pk == same.pk == entry_id
    assert entry.tracking_code == "PAY-TEST"
    assert customer.debt_balance == 30_000


def test_stale_detection_never_probes_network_when_disabled(funded):
    _, device = funded
    ClientDevice.objects.filter(pk=device.pk).update(last_heartbeat_at=timezone.now() - timedelta(minutes=5))
    with patch("apps.devices.wol.is_lan_host_reachable", side_effect=AssertionError("network probe")):
        assert mark_stale_devices_offline(probe=False) == 1
    device.refresh_from_db()
    assert device.connection_status == ConnectionStatus.OFFLINE


def test_heartbeat_refreshes_idle_config_and_has_full_session_snapshot(funded):
    customer, device = funded
    session = start_session(customer, device)
    consumer = consumer_for(device)
    ClientDevice.objects.filter(pk=device.pk).update(metadata={"idle_shutdown_minutes": 42})
    assert consumer._idle_shutdown_minutes() == 42
    sync = consumer._heartbeat("ONLINE", "0.2.8")
    assert sync["session_id"] == str(session.pk)
    assert sync["wallet_balance"] == 100_000
    assert "coupon_hours" in sync and "paused" in sync
    assert sync["remaining_balance"] <= 100_000


def test_restart_retains_sessions_for_recovery(funded):
    customer, device = funded
    session = start_session(customer, device)
    assert reconcile_orphaned_sessions() == 1
    session.refresh_from_db()
    assert session.status == SessionStatus.ACTIVE
    assert session.connection_lost_at is not None
    assert session.paused_at is not None


def logout(device, session_id, **extra):
    request = APIRequestFactory().post("/api/v1/client/user-logout", {
        "session_id": str(session_id), **extra,
    }, format="json")
    with patch("apps.devices.views.device_or_401", return_value=device):
        return ClientUserLogoutView.as_view()(request)


def test_logout_retry_does_not_end_next_session(funded):
    customer, device = funded
    old = start_session(customer, device)
    assert logout(device, old.pk).status_code == 200
    set_status(device, ClientStatus.ONLINE, force=True)
    new = start_session(customer, device)
    assert logout(device, old.pk).status_code == 200
    new.refresh_from_db()
    assert new.status == SessionStatus.ACTIVE


def test_temporary_lock_does_not_settle_session(funded):
    customer, device = funded
    session = start_session(customer, device)
    result = logout(device, session.pk, keep_processes=True)
    assert result.data["temporarily_locked"]
    session.refresh_from_db()
    assert session.status == SessionStatus.ACTIVE
    assert session.ended_at is None


def test_login_can_resume_same_customer_session(funded):
    customer, device = funded
    customer.set_password("secret")
    customer.save()
    session = start_session(customer, device)
    request = APIRequestFactory().post("/api/v1/client/user-login", {
        "username": customer.phone, "password": "secret",
    }, format="json")
    with patch("apps.devices.views.device_or_401", return_value=device):
        result = ClientUserLoginView.as_view()(request)
    assert result.status_code == 200
    assert result.data["session_id"] == str(session.pk)
    assert GamingSession.objects.filter(device=device).count() == 1


def test_stale_session_commands_are_not_replayed(funded):
    customer, device = funded
    old = start_session(customer, device)
    stop_session(old)
    set_status(device, ClientStatus.ONLINE, force=True)
    new = start_session(customer, device)
    consumer = consumer_for(device)
    commands = consumer._pending_commands()
    assert all(cmd["payload"].get("session_id") == str(new.pk) for cmd in commands)
