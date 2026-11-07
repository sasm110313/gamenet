from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.clients.models import ClientStatus
from apps.customers.services import CustomerError, update_customer
from apps.devices.services import set_status
from apps.pricing.services import create_customer_rate, deactivate_customer_rate, update_customer_rate
from apps.sessions.models import GamingSession
from apps.sessions.services import SessionError, start_session
from apps.synchronization.cloud_client import CloudUnavailable
from apps.synchronization.edge_runtime import run_once
from apps.wallets.models import Wallet
from apps.core.redirects import safe_redirect_next
from apps.synchronization.handlers import apply_event


@pytest.mark.django_db
def test_reactivated_rate_recovers_default(customer):
    rate = create_customer_rate(customer=customer, name="VIP", hourly_rate=45000)
    rate = deactivate_customer_rate(rate)
    rate = update_customer_rate(rate, is_active=True)
    assert rate.is_active and rate.is_default


@pytest.mark.django_db
def test_start_reserves_accrued_cost(customer, device, synced_identity):
    set_status(device, ClientStatus.ONLINE, force=True)
    session = start_session(customer, device)
    GamingSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(hours=3))
    from apps.clients.models import ClientDevice
    other = ClientDevice.objects.create(edge_id=synced_identity.edge_id, name="Other", status=ClientStatus.ONLINE)
    with pytest.raises(SessionError):
        start_session(customer, other)


@pytest.mark.django_db
def test_credit_reduction_respects_active_reservation(customer, device):
    set_status(device, ClientStatus.ONLINE, force=True)
    start_session(customer, device)
    with pytest.raises(CustomerError):
        update_customer(customer, credit_limit=0)
    assert Wallet.objects.get(customer=customer).balance == 0


@pytest.mark.django_db
def test_offline_cloud_does_not_stop_local_maintenance(identity):
    with patch("apps.synchronization.edge_runtime.pull_and_queue_commands", side_effect=CloudUnavailable("offline")), \
         patch("apps.synchronization.edge_runtime.execute_received_commands", return_value=1) as execute, \
         patch("apps.synchronization.outbox.drain_outbox", return_value={}), \
         patch("apps.synchronization.edge_runtime.send_heartbeat", side_effect=CloudUnavailable("offline")), \
         patch("apps.synchronization.edge_runtime.sync_config", side_effect=CloudUnavailable("offline")), \
         patch("apps.devices.services.mark_stale_devices_offline", return_value=0) as stale, \
         patch("apps.synchronization.command_service.expire_stale_commands", return_value=0):
        result = run_once(client=object())
    assert result["commands"]["executed"] == 1
    execute.assert_called_once()
    stale.assert_called_once()


@pytest.mark.django_db
def test_projection_rejects_another_edges_customer(settings, edge_node, customer):
    settings.GAMENET_ROLE = "cloud"
    import uuid
    event = SimpleNamespace(
        edge_id=uuid.uuid4(), event_type="customer.updated",
        payload={"customer_id": str(customer.id), "full_name": "Foreign"},
    )
    with pytest.raises(ValueError, match="another edge"):
        apply_event(event)
    customer.refresh_from_db()
    assert customer.full_name != "Foreign"


def test_redirect_rejects_external_url(rf):
    request = rf.post("/", {"next": "//evil.example/path"})
    assert safe_redirect_next(request, "/sessions/")["Location"] == "/sessions/"


@pytest.mark.django_db
def test_fresh_edge_can_register_device_without_dashboard_bootstrap():
    from apps.devices.services import create_registration_code, register_device
    from apps.synchronization.models import EdgeIdentity

    assert not EdgeIdentity.objects.exists()
    code = create_registration_code(label="fresh edge")
    device, token = register_device(code=code.code, name="Fresh PC")
    assert device.edge_id == EdgeIdentity.get_solo().edge_id
    assert token
