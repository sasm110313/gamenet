import os

# Settings are imported by pytest-django after conftest import, so defaults must be
# in the environment before that happens.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-for-production")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://gamenet:gamenet@127.0.0.1:55432/gamenet_test"
)
os.environ.setdefault("GAMENET_ROLE", "edge")
os.environ.setdefault("CLOUD_CA_BUNDLE", "")
os.environ.setdefault("EDGE_CREDENTIALS_FILE", "/tmp/gamenet-test-credentials.json")

import pytest  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.clients.models import ClientDevice, ClientStatus  # noqa: E402
from apps.core.ids import uuid7  # noqa: E402
from apps.synchronization.crypto import generate_command_keypair, hash_token, new_secret  # noqa: E402
from apps.synchronization.edge_credentials import ensure_identity  # noqa: E402
from apps.synchronization.models import EdgeNode, EdgeStatus  # noqa: E402


@pytest.fixture
def identity(db, settings):
    # Cloud-role tests also request this fixture; identity creation is edge-only.
    previous = settings.GAMENET_ROLE
    settings.GAMENET_ROLE = "edge"
    try:
        ident = ensure_identity()
        ident.name = "Test Floor"
        ident.cloud_base_url = "http://cloud.test"
        ident.save()
    finally:
        settings.GAMENET_ROLE = previous
    return ident


@pytest.fixture
def edge_node(db):
    public_key, encrypted = generate_command_keypair()
    secret = new_secret()
    edge = EdgeNode.objects.create(
        name="Test Floor",
        secret_hash=hash_token(secret),
        command_public_key=public_key,
        command_private_key_enc=encrypted,
        status=EdgeStatus.ONLINE,
    )
    edge._plain_secret = secret  # test-only convenience
    return edge


@pytest.fixture
def synced_identity(identity, edge_node):
    identity.edge_id = edge_node.id
    identity.command_public_key = edge_node.command_public_key
    identity.save()
    return identity


@pytest.fixture
def device(synced_identity):
    token = new_secret()
    dev = ClientDevice.objects.create(
        edge_id=synced_identity.edge_id,
        name="PC-01",
        hostname="WIN7-PC01",
        operating_system="Windows 7 SP1",
        application_version="0.1.0",
        status=ClientStatus.OFFLINE,
        token_hash=hash_token(token),
        token_issued_at=timezone.now(),
    )
    dev._plain_token = token
    return dev
