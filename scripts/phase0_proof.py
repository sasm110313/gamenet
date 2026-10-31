#!/usr/bin/env python3
"""Phase 0 acceptance proof for GameNet.

This is deliberately black-box: it talks to the running cloud and edge over
HTTPS/WSS, logs into both dashboards as a human would, drives the real Electron
client through its DevTools port, stops the cloud to prove offline buffering, and
then verifies replication in PostgreSQL through the Django management shell.

It never prints or stores secrets. Run it with the backend virtualenv:

    backend/.venv/bin/python scripts/phase0_proof.py --client-device PC-06

Preconditions (see docs/PHASE0.md):
  * PostgreSQL + Redis up, cloud and edge uvicorn up, one edge worker up
  * the Electron client paired and running with --remote-debugging-port=9223
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import signal
import ssl
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests
import websocket
import websockets

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "docs" / "evidence"
CA_FILE = ROOT / "dev" / "certs" / "ca.pem"
MARKER = "__PROOF__"
CDP_ENDPOINT = os.environ.get("GAMENET_CDP", "http://127.0.0.1:9223/json")

SECRET_WORDS = ("token", "secret", "password")


class ProofError(RuntimeError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ProofError(message)


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


def wait_for(
    probe: Callable[[], Any],
    *,
    timeout: float = 40.0,
    interval: float = 0.75,
    label: str = "condition",
) -> Any:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value:
                return value
        except Exception as exc:  # transient while services restart
            last_error = str(exc)
        time.sleep(interval)
    raise ProofError(f"timed out waiting for {label}" + (f": {last_error}" if last_error else ""))


# ---------------------------------------------------------------------------
# Django shell helper
# ---------------------------------------------------------------------------
def manage(role: str, body: str, timeout: float = 120.0) -> Any:
    """Run a snippet that assigns ``result`` and return it as JSON.

    The marker is printed from inside the snippet; management-command banners on
    stderr never contaminate the payload.
    """
    code = (
        "import json as _proof_json\n"
        + body.strip("\n")
        + "\nprint(" + json.dumps(MARKER) + " + _proof_json.dumps(result, default=str))\n"
    )
    process = subprocess.run(
        [str(ROOT / "dev" / "manage.sh"), role, "shell", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    for line in process.stdout.splitlines():
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER) :])
    detail = (process.stderr or process.stdout or "").strip()[-1600:]
    raise ProofError(f"{role} management command failed: {detail}")


def http_get(url: str, **kwargs: Any) -> requests.Response:
    return requests.get(url, verify=str(CA_FILE), timeout=25, **kwargs)


def http_post(url: str, **kwargs: Any) -> requests.Response:
    return requests.post(url, verify=str(CA_FILE), timeout=25, **kwargs)


def health(base: str, role: str) -> dict[str, Any]:
    response = http_get(f"{base}/healthz")
    require(response.status_code == 200, f"{role} healthz returned HTTP {response.status_code}")
    body = response.json()
    require(body.get("role") == role, f"expected {role} at {base}, got {body.get('role')!r}")
    return body


def ensure_admin(role: str) -> dict[str, Any]:
    body = """
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ.get("ADMIN_USERNAME", "admin")
user = User.objects.filter(username=username).first()
created = False
promoted = False
if user is None:
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        raise SystemExit("ADMIN_PASSWORD is required to create the dashboard admin")
    user = User.objects.create_superuser(
        username=username,
        email=os.environ.get("ADMIN_EMAIL", ""),
        password=password,
    )
    created = True
else:
    if not user.is_staff or not user.is_superuser:
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        promoted = True

result = {
    "created": created,
    "promoted": promoted,
    "username": username,
    "is_staff": bool(user.is_staff),
    "is_superuser": bool(user.is_superuser),
}
"""
    result = manage(role, body)
    require(result["is_staff"] and result["is_superuser"], f"{role} admin {result['username']!r} is not staff")
    return result


def dashboard_login(base: str) -> requests.Session:
    session = requests.Session()
    session.verify = str(CA_FILE)
    session.headers["User-Agent"] = "GameNetPhase0Proof/1.0"
    login_url = f"{base}/admin/login/?next=/"
    page = session.get(login_url, timeout=25)
    require(page.status_code == 200, f"login page {login_url} returned HTTP {page.status_code}")
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text)
    require(match is not None, "admin login page has no CSRF token")
    response = session.post(
        login_url,
        data={
            "username": os.environ.get("ADMIN_USERNAME", "admin"),
            "password": os.environ.get("ADMIN_PASSWORD", ""),
            "csrfmiddlewaretoken": match.group(1),
            "next": "/",
        },
        headers={"Referer": login_url},
        allow_redirects=False,
        timeout=25,
    )
    require(
        response.status_code in (302, 303),
        f"dashboard login at {base} failed (HTTP {response.status_code})",
    )
    home = session.get(f"{base}/", timeout=25)
    require(home.status_code == 200, f"dashboard home at {base} returned HTTP {home.status_code}")
    require("/admin/login/" not in home.url, f"dashboard session at {base} was not authenticated")
    return session


def post_action(session: requests.Session, url: str, data: dict[str, str]) -> None:
    token = session.cookies.get("csrftoken")
    require(token, "dashboard session has no CSRF cookie")
    response = session.post(
        url,
        data={**data, "csrfmiddlewaretoken": token},
        headers={"Referer": url, "X-CSRFToken": token},
        allow_redirects=False,
        timeout=25,
    )
    require(
        response.status_code in (302, 303),
        f"POST {url} returned HTTP {response.status_code}, expected a redirect",
    )


def text_fragment(html: str, needle: str, width: int = 160) -> str:
    index = html.find(needle)
    require(index >= 0, f"{needle!r} not found in dashboard HTML")
    fragment = html[max(0, index - width) : index + width]
    fragment = re.sub(r"<script.*?</script>", " ", fragment, flags=re.S)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def new_event_note(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def cloud_event_count() -> int:
    return manage(
        "cloud",
        """
from apps.synchronization.models import SyncEvent

result = {"events": SyncEvent.objects.count()}
""",
    )["events"]


# ---------------------------------------------------------------------------
# CDP helpers (real Electron renderer)
# ---------------------------------------------------------------------------
def cdp_target() -> str:
    targets = requests.get(CDP_ENDPOINT, timeout=5).json()
    page = next((item for item in targets if item.get("type") == "page"), None)
    require(page is not None, "no Electron page target on the CDP port")
    return page["webSocketDebuggerUrl"]


def cdp_call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    socket = websocket.create_connection(cdp_target(), timeout=10)
    try:
        socket.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            message = json.loads(socket.recv())
            if message.get("id") == 1:
                if "error" in message:
                    raise ProofError(f"CDP {method} failed: {message['error']}")
                return message.get("result", {})
    finally:
        socket.close()


def ui_text() -> str:
    result = cdp_call(
        "Runtime.evaluate",
        {"expression": "document.body.innerText", "returnByValue": True},
    )
    return str(result.get("result", {}).get("value", ""))


def ui_expect(needle: str, timeout: float = 25.0) -> str:
    def probe() -> str | None:
        text = ui_text()
        return text if needle in text else None

    return wait_for(probe, timeout=timeout, label=f"client UI to show {needle!r}")


def capture(name: str) -> str:
    result = cdp_call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    target = EVIDENCE_DIR / name
    target.write_bytes(base64.b64decode(result["data"]))
    return str(target.relative_to(ROOT))


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------
def listener_pid(port: int) -> int | None:
    process = subprocess.run(
        ["ss", "-ltnpH", f"sport = :{port}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    match = re.search(r"pid=(\d+)", process.stdout)
    return int(match.group(1)) if match else None


def cloud_is_up(base: str) -> bool:
    try:
        return health(base, "cloud").get("status") == "ok"
    except Exception:
        return False


def stop_cloud(base: str, port: int) -> int:
    pid = listener_pid(port)
    require(pid is not None, "cloud listener is not running")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if not cloud_is_up(base) and listener_pid(port) is None:
            return pid
        time.sleep(0.4)
    raise ProofError("cloud did not stop within 20 seconds")


def start_cloud(base: str) -> None:
    if cloud_is_up(base):
        return
    log_path = ROOT / ".artifacts" / "proof-cloud.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    subprocess.Popen(
        [str(ROOT / "dev" / "run_cloud.sh")],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_for(lambda: cloud_is_up(base), timeout=60, label="cloud to restart")


# ---------------------------------------------------------------------------
# Proof steps
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-device", help="device name shown in the running Electron app (default: auto)")
    parser.add_argument("--no-ui", action="store_true", help="skip Electron/CDP checks and screenshots")
    parser.add_argument("--output", default=str(EVIDENCE_DIR / "phase0.json"))
    args = parser.parse_args()

    load_dotenv()
    cloud_port = int(os.environ.get("CLOUD_PORT", "18443"))
    edge_port = int(os.environ.get("EDGE_PORT", "19443"))
    CLOUD = f"https://127.0.0.1:{cloud_port}"
    EDGE = f"https://127.0.0.1:{edge_port}"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    evidence: dict[str, Any] = {
        "phase": 0,
        "started_at": iso(),
        "finished_at": None,
        "passed": False,
        "environment": {},
        "steps": [],
        "artifacts": [],
    }
    started_monotonic = time.monotonic()
    cloud_session: requests.Session | None = None
    edge_session: requests.Session | None = None
    edge_id = ""
    edge_secret = ""
    proof_device_id = ""
    proof_device_name = ""
    proof_token = ""
    client_id: str | None = None

    def record(number: int, key: str, title: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        print(f"[{number:02d}/10] {title} ...", flush=True)
        begin = time.monotonic()
        try:
            details = fn() or {}
        except Exception as exc:
            evidence["steps"].append(
                {
                    "number": number,
                    "key": key,
                    "title": title,
                    "ok": False,
                    "seconds": round(time.monotonic() - begin, 2),
                    "error": str(exc),
                }
            )
            print(f"          FAIL: {exc}", flush=True)
            raise
        evidence["steps"].append(
            {
                "number": number,
                "key": key,
                "title": title,
                "ok": True,
                "seconds": round(time.monotonic() - begin, 2),
                "details": details,
            }
        )
        print(f"          PASS ({time.monotonic() - begin:.1f}s)", flush=True)
        return details

    try:
        # -- preflight ------------------------------------------------------
        require(CA_FILE.exists(), f"development CA missing at {CA_FILE}")
        cloud_health = health(CLOUD, "cloud")
        edge_health = health(EDGE, "edge")

        credentials_path = ROOT / os.environ.get(
            "EDGE_CREDENTIALS_FILE", ".artifacts/edge-credentials.json"
        )
        require(credentials_path.exists(), f"edge credentials missing at {credentials_path}")
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        edge_id = str(credentials["edge_id"])
        edge_secret = str(credentials["secret"])
        require(edge_secret, "edge credential file has no secret")

        admin_status = {"cloud": ensure_admin("cloud"), "edge": ensure_admin("edge")}
        cloud_session = dashboard_login(CLOUD)
        edge_session = dashboard_login(EDGE)

        evidence["environment"] = {
            "cloud": {"base": CLOUD, **{k: cloud_health.get(k) for k in ("status", "role", "version")}},
            "edge": {"base": EDGE, **{k: edge_health.get(k) for k in ("status", "role", "version")}},
            "edge_id": edge_id,
            "admins": admin_status,
            "tls": "CA-verified HTTPS/WSS (the Electron client additionally pins the edge certificate)",
        }

        # 1 ------------------------------------------------------------------
        def step_edge_registration() -> dict[str, Any]:
            cloud_record = manage(
                "cloud",
                f"""
from apps.synchronization.models import EdgeNode

edge = EdgeNode.objects.get(id={json.dumps(edge_id)})
result = {{
    "id": str(edge.id),
    "name": edge.name,
    "status": edge.status,
    "credential_hash_length": len(edge.secret_hash),
    "command_public_key_length": len(edge.command_public_key),
    "last_acked_sequence": edge.last_acked_sequence,
    "last_sync_at": edge.last_sync_at.isoformat() if edge.last_sync_at else None,
}}
""",
            )
            local_identity = manage(
                "edge",
                """
from apps.synchronization.edge_credentials import ensure_identity

identity = ensure_identity()
result = {
    "edge_id": str(identity.edge_id),
    "name": identity.name,
    "command_public_key_length": len(identity.command_public_key),
}
""",
            )
            require(local_identity["edge_id"] == cloud_record["id"], "edge local identity and cloud record differ")
            require(cloud_record["credential_hash_length"] == 64, "cloud edge credential hash is not SHA-256")
            require(cloud_record["command_public_key_length"] > 20, "cloud edge has no command public key")
            config = http_get(
                f"{CLOUD}/api/v1/edge/config?after=0",
                headers={"Authorization": f"Edge {edge_id}.{edge_secret}"},
            )
            require(config.status_code == 200, f"edge-authenticated config call returned HTTP {config.status_code}")
            return {
                "cloud_record": cloud_record,
                "local_identity": local_identity,
                "authenticated_config_http": config.status_code,
                "config_up_to_date": config.json().get("up_to_date"),
            }

        record(1, "edge_registration", "Edge registration and credential authentication", step_edge_registration)

        # 2 ------------------------------------------------------------------
        def step_device_registration() -> dict[str, Any]:
            nonlocal proof_device_id, proof_device_name, proof_token

            cleanup = manage(
                "edge",
                """
from apps.clients.models import ClientDevice
from apps.devices.services import deactivate_device

old = list(
    ClientDevice.objects.filter(name__startswith="PROOF-PC-", is_active=True)
    .values_list("name", flat=True)
)
for device in ClientDevice.objects.filter(name__startswith="PROOF-PC-", is_active=True):
    deactivate_device(device)
result = {"deactivated": old}
""",
            )
            created = manage(
                "edge",
                """
from apps.devices.services import create_registration_code

code = create_registration_code(label="phase0 proof")
result = {"code": code.code, "expires_at": code.expires_at.isoformat()}
""",
            )
            proof_device_name = f"PROOF-PC-{utcnow():%H%M%S}-{uuid.uuid4().hex[:4]}"
            response = http_post(
                f"{EDGE}/api/v1/device/register",
                json={
                    "code": created["code"],
                    "name": proof_device_name,
                    "hostname": "PROOF-WIN7",
                    "operating_system": "Windows 7 SP1 x64 (proof)",
                    "application_version": "0.1.0-proof",
                },
            )
            require(
                response.status_code == 201,
                f"device registration returned HTTP {response.status_code}: {response.text[:300]}",
            )
            body = response.json()
            require(body.get("device_id") and body.get("token"), "device registration response is incomplete")
            proof_device_id = str(body["device_id"])
            proof_token = str(body["token"])
            require(body.get("ws_path") == "/ws/device/", "unexpected device WebSocket path")
            require(body.get("hub_name"), "registration response has no hub name")

            replica = wait_for(
                lambda: (
                    lambda value: value
                    if value and value.get("exists") and value.get("is_replica") is True
                    else None
                )(
                    manage(
                        "cloud",
                        f"""
from apps.clients.models import ClientDevice

device = ClientDevice.objects.filter(id={json.dumps(proof_device_id)}).first()
result = {{
    "exists": device is not None,
    "name": device.name if device else None,
    "is_replica": device.is_replica if device else None,
    "status": device.status if device else None,
}}
""",
                    )
                ),
                timeout=60,
                label="cloud replica of the proof device",
            )
            require(replica.get("is_replica") is True, "cloud device was not written by the replica path")
            # proof_token lives only in this closure; it is never written to evidence.
            return {
                "deactivated_previous_proof_devices": cleanup["deactivated"],
                "device": {"id": proof_device_id, "name": proof_device_name, "hostname": "PROOF-WIN7"},
                "credential_issued": True,
                "credential_length": len(proof_token),
                "cloud_replica": replica,
                "ws_path": body["ws_path"],
                "hub_name": body.get("hub_name"),
                "heartbeat_seconds": body.get("device_heartbeat_seconds"),
            }

        record(2, "device_registration", "Device registration over edge HTTPS", step_device_registration)
        require(proof_token, "proof token was lost")

        # 3 ------------------------------------------------------------------
        def step_heartbeat() -> dict[str, Any]:
            async def websocket_roundtrip() -> tuple[dict[str, Any], dict[str, Any]]:
                context = ssl.create_default_context(cafile=str(CA_FILE))
                async with websockets.connect(
                    f"wss://127.0.0.1:{edge_port}/ws/device/",
                    ssl=context,
                    open_timeout=15,
                    close_timeout=5,
                    max_size=256 * 1024,
                ) as socket:
                    await socket.send(
                        json.dumps(
                            {
                                "type": "hello",
                                "device_id": proof_device_id,
                                "token": proof_token,
                                "state": "LOCKED",
                                "app_version": "0.1.0-proof",
                            }
                        )
                    )
                    welcome = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
                    await socket.send(
                        json.dumps({"type": "heartbeat", "state": "LOCKED", "app_version": "0.1.0-proof"})
                    )
                    ack = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
                    return welcome, ack

            welcome, ack = asyncio.run(websocket_roundtrip())
            require(welcome.get("type") == "welcome", "device WebSocket did not send welcome")
            require(welcome.get("device_id") == proof_device_id, "welcome addressed the wrong device")
            require(welcome.get("hub_name"), "welcome did not include the hub name")
            require(int(welcome.get("heartbeat_seconds", 0)) >= 3, "welcome heartbeat interval is invalid")
            require(ack.get("type") == "heartbeat_ack", "device WebSocket did not acknowledge heartbeat")

            # Closing the socket marks the device offline. Wait for that state so
            # the following REST heartbeat is the transition that actually counts.
            wait_for(
                lambda: manage(
                    "edge",
                    f"""
from apps.clients.models import ClientDevice

device = ClientDevice.objects.get(id={json.dumps(proof_device_id)})
result = {{"offline": device.status == "OFFLINE", "status": device.status}}
""",
                )["offline"],
                timeout=20,
                label="device to be marked offline after WebSocket close",
            )

            rest = http_post(
                f"{EDGE}/api/v1/device/heartbeat",
                json={"state": "ONLINE", "app_version": "0.1.0-proof"},
                headers={"Authorization": f"Device {proof_device_id}.{proof_token}"},
            )
            require(rest.status_code == 200, f"REST heartbeat returned HTTP {rest.status_code}")
            heartbeat_body = rest.json()
            edge_state = wait_for(
                lambda: (
                    lambda value: value
                    if value and value.get("status") == "ONLINE" and value.get("last_heartbeat_at")
                    else None
                )(
                    manage(
                        "edge",
                        f"""
from apps.clients.models import ClientDevice

device = ClientDevice.objects.get(id={json.dumps(proof_device_id)})
result = {{
    "status": device.status,
    "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
    "application_version": device.application_version,
}}
""",
                    )
                ),
                timeout=20,
                label="edge heartbeat state",
            )
            require(edge_state["last_heartbeat_at"], "heartbeat timestamp was not persisted")
            require(edge_state["status"] == "ONLINE", f"unexpected edge status {edge_state['status']}")
            return {
                "websocket": {
                    "welcome_type": welcome.get("type"),
                    "hub_name": welcome.get("hub_name"),
                    "desired_state": welcome.get("desired_state"),
                    "heartbeat_seconds": welcome.get("heartbeat_seconds"),
                    "heartbeat_ack": ack.get("type"),
                    "server_time_present": bool(ack.get("server_time")),
                },
                "rest": {
                    "http": rest.status_code,
                    "desired_state": heartbeat_body.get("desired_state"),
                    "config_version": heartbeat_body.get("config_version"),
                },
                "persisted": edge_state,
            }

        record(3, "heartbeat", "Device heartbeat over WSS and HTTPS", step_heartbeat)

        # 4 ------------------------------------------------------------------
        def step_local_dashboard() -> dict[str, Any]:
            page = edge_session.get(f"{EDGE}/devices/", params={"q": proof_device_name}, timeout=25)
            require(page.status_code == 200, f"edge dashboard returned HTTP {page.status_code}")
            require(proof_device_name in page.text, "edge dashboard does not show the proof device")
            require("آنلاین" in page.text, "edge dashboard does not show an online status")
            return {
                "http": page.status_code,
                "url": f"{EDGE}/devices/?q={proof_device_name}",
                "device_visible": True,
                "status_online_visible": True,
                "snippet": text_fragment(page.text, proof_device_name),
            }

        record(4, "local_dashboard", "Local edge dashboard shows the live device", step_local_dashboard)

        # 5 ------------------------------------------------------------------
        def step_cloud_dashboard() -> dict[str, Any]:
            edge_replica = wait_for(
                lambda: (
                    lambda value: value
                    if value and value.get("status") == "ONLINE" and value.get("last_heartbeat_at")
                    else None
                )(
                    manage(
                        "cloud",
                        f"""
from apps.clients.models import ClientDevice

device = ClientDevice.objects.filter(id={json.dumps(proof_device_id)}).first()
result = {{
    "exists": device is not None,
    "status": device.status if device else None,
    "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device and device.last_heartbeat_at else None,
}}
""",
                    )
                ),
                timeout=60,
                label="cloud replica status after heartbeat",
            )
            require(edge_replica.get("status") == "ONLINE", "cloud replica did not receive the heartbeat status")
            page = cloud_session.get(f"{CLOUD}/edges/{edge_id}/", timeout=25)
            require(page.status_code == 200, f"cloud edge dashboard returned HTTP {page.status_code}")
            require(proof_device_name in page.text, "cloud edge dashboard does not show the replicated device")
            require("سالن اصلی" in page.text, "cloud edge dashboard does not show the edge name")
            overview = cloud_session.get(f"{CLOUD}/", timeout=25)
            require(overview.status_code == 200, f"cloud overview returned HTTP {overview.status_code}")
            require("سالن اصلی" in overview.text, "cloud overview does not show the edge")
            return {
                "cloud_replica": edge_replica,
                "edge_dashboard_http": page.status_code,
                "device_visible": True,
                "edge_name_visible": True,
                "overview_http": overview.status_code,
                "snippet": text_fragment(page.text, proof_device_name),
            }

        record(5, "cloud_dashboard", "Cloud dashboard shows the replicated device", step_cloud_dashboard)

        # 6 ------------------------------------------------------------------
        def latest_remote_command(command_type: str, since: str) -> dict[str, Any] | None:
            return manage(
                "cloud",
                f"""
from apps.commands.models import RemoteCommand

command = RemoteCommand.objects.filter(
    edge_id={json.dumps(edge_id)},
    command_type={json.dumps(command_type)},
    issued_at__gte={json.dumps(since)},
).order_by("-issued_at").first()
result = {{
    "id": str(command.id) if command else None,
    "status": command.status if command else None,
    "result": command.result if command else None,
    "error": command.error if command else None,
    "issued_at": command.issued_at.isoformat() if command else None,
}}
""",
            )

        def step_edge_command() -> dict[str, Any]:
            since = iso()
            post_action(cloud_session, f"{CLOUD}/edges/{edge_id}/action", {"action": "ping"})
            command = wait_for(
                lambda: (
                    lambda value: value
                    if value and value.get("id") and value.get("status") == "ACKNOWLEDGED"
                    else None
                )(latest_remote_command("edge.ping", since)),
                timeout=60,
                label="cloud edge.ping acknowledgement",
            )
            require(command["result"] and command["result"].get("pong") is True, "edge ping did not return pong")
            require(command["result"].get("edge_id") == edge_id, "edge ping returned a different edge id")
            inbound = manage(
                "edge",
                """
from apps.commands.models import InboundRemoteCommand

command = InboundRemoteCommand.objects.filter(command_type="edge.ping").order_by("-received_at").first()
result = {
    "command_id": str(command.command_id) if command else None,
    "status": command.status if command else None,
    "executed_at": command.executed_at.isoformat() if command and command.executed_at else None,
}
""",
            )
            require(inbound["status"] == "SUCCEEDED", f"edge inbound command is {inbound['status']}")
            return {"cloud_command": command, "edge_inbound": inbound}

        record(6, "remote_command_edge", "Cloud dashboard command reaches and executes on the edge", step_edge_command)

        # 7 ------------------------------------------------------------------
        def find_client_device() -> dict[str, Any]:
            devices = manage(
                "edge",
                """
from apps.clients.models import ClientDevice

rows = []
for device in ClientDevice.objects.filter(is_active=True).order_by("-last_heartbeat_at"):
    rows.append({
        "id": str(device.id),
        "name": device.name,
        "status": device.status,
        "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        "application_version": device.application_version,
    })
result = rows
""",
            )
            wanted = args.client_device
            for row in devices:
                if wanted and row["name"] != wanted:
                    continue
                if not wanted and row["name"].startswith("PROOF-PC-"):
                    continue
                heartbeat = row.get("last_heartbeat_at")
                if not heartbeat:
                    continue
                seen = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
                if utcnow() - seen <= timedelta(seconds=120):
                    return row
            raise ProofError(
                "no recently connected client found"
                + (f" with name {wanted!r}" if wanted else "")
                + "; start the Electron client or pass --client-device"
            )

        def step_client_command() -> dict[str, Any]:
            nonlocal client_id
            client = find_client_device()
            client_id = str(client["id"])

            if not args.no_ui:
                text = ui_expect(client["name"])
                require("این رایانه قفل است" in text or "آماده بازی" in text, "client UI is not on a known screen")

            def issue(action: str, command_type: str) -> dict[str, Any]:
                since = iso()
                post_action(
                    cloud_session,
                    f"{CLOUD}/devices/{client_id}/action",
                    {"action": action, "next": "/"},
                )
                return wait_for(
                    lambda: (
                        lambda value: value
                        if value and value.get("id") and value.get("status") == "ACKNOWLEDGED"
                        else None
                    )(latest_remote_command(command_type, since)),
                    timeout=60,
                    label=f"client {action} acknowledgement",
                )

            unlocked = issue("unlock", "client.unlock")
            require(
                (unlocked.get("result") or {}).get("locked") is False,
                f"client unlock result was {unlocked.get('result')!r}",
            )
            if not args.no_ui:
                ui_expect("آماده بازی")
                evidence["artifacts"].append(capture("phase0-client-unlocked.png"))

            locked = issue("lock", "client.lock")
            require(
                (locked.get("result") or {}).get("locked") is True,
                f"client lock result was {locked.get('result')!r}",
            )
            if not args.no_ui:
                ui_expect("این رایانه قفل است")
                evidence["artifacts"].append(capture("phase0-client-locked.png"))

            ping = issue("ping", "client.ping")
            result = ping.get("result") or {}
            require(result.get("pong") is True, "client ping did not return pong")
            require(result.get("app_version"), "client ping did not return the app version")

            device_command = manage(
                "edge",
                f"""
from apps.commands.models import DeviceCommand

command = DeviceCommand.objects.filter(client_id={json.dumps(client_id)}).order_by("-issued_at").first()
result = {{
    "id": str(command.id) if command else None,
    "type": command.command_type if command else None,
    "status": command.status if command else None,
    "result": command.result if command else None,
}}
""",
            )
            require(device_command["status"] == "ACKNOWLEDGED", "edge device command is not acknowledged")
            return {
                "client": client,
                "unlock": {"status": unlocked["status"], "result": unlocked["result"]},
                "lock": {"status": locked["status"], "result": locked["result"]},
                "ping": {"status": ping["status"], "result": result},
                "edge_device_command": device_command,
                "ui_assertions": "skipped" if args.no_ui else ["unlocked screen", "locked screen"],
            }

        record(
            7, "command_forwarded_client", "Cloud command is forwarded to the real Electron client", step_client_command
        )

        # 8 ------------------------------------------------------------------
        def step_edge_event() -> dict[str, Any]:
            since = iso()
            post_action(cloud_session, f"{CLOUD}/edges/{edge_id}/action", {"action": "test_event"})
            event = wait_for(
                lambda: (
                    lambda value: value if value and value.get("event_id") else None
                )(
                    manage(
                        "cloud",
                        f"""
from apps.synchronization.models import SyncEvent

event = SyncEvent.objects.filter(
    edge_id={json.dumps(edge_id)},
    event_type="edge.test",
    payload__origin="cloud_command",
    received_at__gte={json.dumps(since)},
).order_by("-received_at").first()
result = {{
    "event_id": str(event.event_id) if event else None,
    "local_sequence": event.local_sequence if event else None,
    "event_type": event.event_type if event else None,
    "aggregate_type": event.aggregate_type if event else None,
    "aggregate_id": event.aggregate_id if event else None,
    "schema_version": event.schema_version if event else None,
    "occurred_at": event.occurred_at.isoformat() if event else None,
    "payload": event.payload if event else None,
    "status": event.status if event else None,
    "received_at": event.received_at.isoformat() if event else None,
}}
""",
                    )
                ),
                timeout=80,
                label="edge.test event replicated to cloud",
            )
            require(event.get("event_id"), "event did not replicate")
            require(event["payload"].get("origin") == "cloud_command", "event origin is wrong")
            return event

        edge_event = record(
            8, "edge_to_cloud_event", "Edge event replicates to the cloud through the outbox", step_edge_event
        )

        # 9 ------------------------------------------------------------------
        def step_duplicate() -> dict[str, Any]:
            envelope = {
                "event_id": edge_event["event_id"],
                "local_sequence": edge_event["local_sequence"],
                "event_type": edge_event["event_type"],
                "aggregate_type": edge_event["aggregate_type"],
                "aggregate_id": edge_event["aggregate_id"],
                "schema_version": edge_event["schema_version"],
                "occurred_at": edge_event["occurred_at"],
                "payload": edge_event["payload"],
            }
            before = cloud_event_count()
            replay = http_post(
                f"{CLOUD}/api/v1/edge/events:batch",
                json={"events": [envelope]},
                headers={"Authorization": f"Edge {edge_id}.{edge_secret}"},
            )
            require(replay.status_code == 200, f"duplicate replay returned HTTP {replay.status_code}")
            replayed = replay.json()
            require(
                edge_event["event_id"] in (replayed.get("duplicates") or []),
                f"cloud did not report the event as a duplicate: {replayed}",
            )
            require(not replayed.get("accepted"), "cloud accepted a duplicate event")

            reuse = dict(envelope)
            reuse["event_id"] = str(uuid.uuid4())
            reused = http_post(
                f"{CLOUD}/api/v1/edge/events:batch",
                json={"events": [reuse]},
                headers={"Authorization": f"Edge {edge_id}.{edge_secret}"},
            )
            require(reused.status_code == 200, f"sequence reuse returned HTTP {reused.status_code}")
            reuse_body = reused.json()
            require(reuse_body.get("rejected"), "cloud accepted a reused local_sequence")
            require(
                "sequence already used" in str(reuse_body["rejected"][0].get("reason", "")),
                f"unexpected sequence-reuse reason: {reuse_body}",
            )
            after = cloud_event_count()
            require(before == after, f"event count changed on replay: {before} -> {after}")
            return {
                "duplicate_response": replayed,
                "sequence_reuse_response": reuse_body,
                "sync_event_count_before": before,
                "sync_event_count_after": after,
            }

        record(9, "duplicate_protection", "Duplicate and sequence-reused events are rejected", step_duplicate)

        # 10 -----------------------------------------------------------------
        def step_offline_queue() -> dict[str, Any]:
            down_pid = stop_cloud(CLOUD, cloud_port)
            down_at = time.monotonic()
            require(not cloud_is_up(CLOUD), "cloud still answers after shutdown")

            note = new_event_note("offline")
            emitted = manage(
                "edge",
                f"""
from django.db import transaction
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit

identity = ensure_identity()
with transaction.atomic():
    event = emit(
        "edge.test",
        aggregate_type="edge",
        aggregate_id=str(identity.edge_id),
        payload={{"note": {json.dumps(note)}, "origin": "offline_proof"}},
    )
result = {{"event_id": str(event.event_id), "local_sequence": event.local_sequence}}
""",
            )
            pending = wait_for(
                lambda: (
                    lambda value: value
                    if value and value.get("status") == "PENDING" and not value.get("cloud_acknowledged_at")
                    else None
                )(
                    manage(
                        "edge",
                        f"""
from apps.synchronization.models import OutboxEvent

event = OutboxEvent.objects.get(event_id={json.dumps(emitted['event_id'])})
result = {{
    "status": event.status,
    "attempts": event.attempts,
    "cloud_acknowledged_at": event.cloud_acknowledged_at.isoformat() if event.cloud_acknowledged_at else None,
}}
""",
                    )
                ),
                timeout=25,
                label="offline event to be pending",
            )
            require(pending["status"] == "PENDING", f"offline event status is {pending['status']}")
            require(pending["cloud_acknowledged_at"] is None, "offline event was already acknowledged")

            start_cloud(CLOUD)
            up_seconds = round(time.monotonic() - down_at, 2)
            require(cloud_is_up(CLOUD), "cloud did not come back")

            replicated = wait_for(
                lambda: (
                    lambda value: value if value and value.get("exists") else None
                )(
                    manage(
                        "cloud",
                        f"""
from apps.synchronization.models import SyncEvent

event = SyncEvent.objects.filter(
    edge_id={json.dumps(edge_id)},
    event_id={json.dumps(emitted['event_id'])},
).first()
result = {{
    "exists": event is not None,
    "event_id": str(event.event_id) if event else None,
    "payload": event.payload if event else None,
}}
""",
                    )
                ),
                timeout=120,
                interval=1.0,
                label="offline event to replicate after cloud restart",
            )
            require(replicated.get("exists"), "offline event never reached the cloud")
            final = manage(
                "edge",
                f"""
from apps.synchronization.models import OutboxEvent

event = OutboxEvent.objects.get(event_id={json.dumps(emitted['event_id'])})
result = {{
    "status": event.status,
    "attempts": event.attempts,
    "cloud_acknowledged_at": event.cloud_acknowledged_at.isoformat() if event.cloud_acknowledged_at else None,
}}
""",
            )
            require(final["status"] == "SYNCED", f"offline event final status is {final['status']}")
            require(final["cloud_acknowledged_at"], "offline event has no cloud acknowledgement")
            return {
                "cloud_stopped_pid": down_pid,
                "cloud_down_seconds": up_seconds,
                "event": emitted,
                "while_offline": pending,
                "after_restart": final,
                "cloud_replica": replicated,
            }

        record(10, "offline_queue", "Offline events stay queued and sync after the cloud returns", step_offline_queue)

        evidence["passed"] = len(evidence["steps"]) == 10 and all(step.get("ok") for step in evidence["steps"])
    except Exception as exc:
        evidence["failed_error"] = str(exc)
        print(f"\nPROOF FAILED: {exc}", file=sys.stderr, flush=True)
    finally:
        # Never leave the venue offline or the demo PC unlocked after a failed run.
        if cloud_session is not None and client_id and cloud_is_up(CLOUD):
            try:
                post_action(
                    cloud_session,
                    f"{CLOUD}/devices/{client_id}/action",
                    {"action": "lock", "next": "/"},
                )
            except Exception:
                pass
        if not cloud_is_up(CLOUD):
            try:
                start_cloud(CLOUD)
            except Exception as exc:
                evidence["restart_error"] = str(exc)
        evidence["finished_at"] = iso()
        evidence["duration_seconds"] = round(time.monotonic() - started_monotonic, 2)
        write_evidence(evidence, Path(args.output))

    passed = len(evidence["steps"]) == 10 and all(step.get("ok") for step in evidence["steps"])
    print("\n" + "=" * 64)
    print(f"Phase 0 proof: {sum(1 for step in evidence['steps'] if step.get('ok'))}/{10} checks passed")
    print(f"Evidence: {Path(args.output)}")
    print("=" * 64)
    return 0 if passed else 1


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if any(secret in key.lower() for secret in SECRET_WORDS):
                clean[key] = "<redacted>"
            else:
                clean[key] = redact(item)
        return clean
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def write_evidence(evidence: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    safe = redact({key: value for key, value in evidence.items() if not key.startswith("_")})
    output.write_text(json.dumps(safe, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    markdown = output.with_suffix(".md")
    passed = safe.get("passed")
    lines = [
        "# Phase 0 acceptance proof",
        "",
        f"- Result: **{'PASS — 10/10' if passed else 'FAIL'}**",
        f"- Started: `{safe.get('started_at')}`",
        f"- Finished: `{safe.get('finished_at')}`",
        f"- Duration: {safe.get('duration_seconds', 0)}s",
        "",
        "## Environment",
        "",
        "```json",
        json.dumps(safe.get("environment", {}), ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Checks",
        "",
        "| # | Check | Result | Seconds |",
        "|---|-------|--------|---------|",
    ]
    for step in safe.get("steps", []):
        mark = "✅" if step.get("ok") else "❌"
        lines.append(f"| {step['number']} | {step['title']} | {mark} | {step.get('seconds', '')} |")
    lines.append("")
    for step in safe.get("steps", []):
        lines.extend(
            [
                f"### {step['number']}. {step['title']}",
                "",
                f"**{'PASS' if step.get('ok') else 'FAIL'}** in {step.get('seconds')}s",
                "",
            ]
        )
        if step.get("details") is not None:
            lines.extend(
                [
                    "```json",
                    json.dumps(step["details"], ensure_ascii=False, indent=2, default=str),
                    "```",
                    "",
                ]
            )
        if step.get("error"):
            lines.extend(["```text", step["error"], "```", ""])
    if safe.get("artifacts"):
        lines.extend(["## Screenshots", ""])
        for artifact in safe["artifacts"]:
            lines.extend([f"![{Path(artifact).stem}]({Path(artifact).name})", ""])
    lines.extend(
        [
            "## Not covered by this run",
            "",
            "- Windows 7 SP1 / Windows 10 hardware behaviour (Electron launch, DPAPI, service restart, x86 installer).",
            "- A real network outage between edge and cloud is simulated by stopping the cloud process; "
            "it is not a cable pull on Windows.",
            "",
            "See `docs/PHASE0.md` for the hardware checklist that still needs to be executed on site.",
            "",
        ]
    )
    markdown.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
