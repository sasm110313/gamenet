#!/usr/bin/env python3
"""Real end-to-end connectivity verification between:
1. Online Cloud Server (https://gamenet.hammasjedy.ir)
2. Local Edge Hub (https://127.0.0.1:19443)
3. Gaming Client Device (WSS client connection)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import time
import urllib3
import requests
import websockets

# Suppress insecure local TLS warnings for loopback edge
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gamenet.real_test")

CLOUD_BASE = os.environ.get("CLOUD_BASE_URL", "https://gamenet.hammasjedy.ir").rstrip("/")
EDGE_BASE = "https://127.0.0.1:19443"
EDGE_WS = "wss://127.0.0.1:19443/ws/device/"

ADMIN_USER = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASS = "j7F1y06PsO3WpQg3YYCpHmjT"


def check_cloud_health():
    logger.info("=== STEP 1: Checking Online Cloud Health ===")
    r = requests.get(f"{CLOUD_BASE}/healthz", timeout=10)
    assert r.status_code == 200, f"Cloud healthz failed: {r.status_code} {r.text}"
    data = r.json()
    logger.info(f"Cloud health: OK (role={data.get('role')}, version={data.get('version')})")


def cloud_login():
    logger.info("=== STEP 2: Authenticating with Cloud Web Dashboard ===")
    s = requests.Session()
    r = s.get(f"{CLOUD_BASE}/admin/login/?next=/", timeout=10)
    m = re.search(r'name=["\']csrfmiddlewaretoken["\'] value=["\']([^"\']+)["\']', r.text)
    assert m, "CSRF token not found on cloud login page"
    csrf = m.group(1)

    r_post = s.post(
        f"{CLOUD_BASE}/admin/login/?next=/",
        data={"username": ADMIN_USER, "password": ADMIN_PASS, "csrfmiddlewaretoken": csrf},
        headers={"Referer": f"{CLOUD_BASE}/admin/login/?next=/"},
        timeout=10,
    )
    assert r_post.status_code == 200, f"Login failed: status {r_post.status_code}"
    assert "sessionid" in s.cookies, "Session cookie missing after login"
    logger.info("Cloud admin authenticated successfully!")
    return s


def verify_cloud_pages(cloud_session: requests.Session):
    logger.info("=== STEP 3: Verifying Cloud Web Pages ===")
    r_over = cloud_session.get(f"{CLOUD_BASE}/", timeout=10)
    assert r_over.status_code == 200, f"Overview failed: {r_over.status_code}"
    assert "داشبورد" in r_over.text, "Dashboard title missing in overview"

    r_dev = cloud_session.get(f"{CLOUD_BASE}/devices/", timeout=10)
    assert r_dev.status_code == 200, f"Devices page failed: {r_dev.status_code}"
    assert "کلاینت‌ها" in r_dev.text, "Devices heading missing"

    r_grid = cloud_session.get(f"{CLOUD_BASE}/devices/grid", timeout=10)
    assert r_grid.status_code == 200, f"Device grid partial failed: {r_grid.status_code}"
    logger.info("Cloud Web Dashboard, Devices, and Grid pages verified OK!")


def register_local_client() -> tuple[str, str, str]:
    logger.info("=== STEP 4: Pairing a Gaming Client with Local Edge Hub ===")
    unique_num = int(time.time()) % 10000
    device_name = f"PC-TEST-{unique_num}"
    # Create code on edge using edge python shell
    cmd = [
        "backend/.venv/bin/python",
        "-c",
        f"""
import os, sys, django
sys.path.insert(0, 'backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamenet.settings.edge')
django.setup()
from apps.devices.services import create_registration_code
reg = create_registration_code(label='{device_name}')
print('PAIR_CODE:' + reg.code)
""",
    ]
    out = subprocess.check_output(cmd, text=True)
    m = re.search(r"PAIR_CODE:([A-Z0-9]+)", out)
    assert m, f"Pair code not found in {out}"
    pair_code = m.group(1)
    logger.info(f"Generated Pairing Code on Edge for {device_name}: {pair_code}")

    # Register client device via edge API
    payload = {
        "code": pair_code,
        "name": device_name,
        "hostname": f"STATION-{unique_num}",
        "operating_system": "Windows 7 SP1",
        "application_version": "0.2.0-phase2",
        "mac_address": f"00:1A:2B:3C:4D:{unique_num % 100:02X}",
    }
    r = requests.post(f"{EDGE_BASE}/api/v1/device/register", json=payload, verify=False, timeout=10)
    assert r.status_code == 201, f"Device registration failed: {r.status_code} {r.text}"
    reg_data = r.json()
    device_id = reg_data["device_id"]
    token = reg_data["token"]
    logger.info(f"Client Registered: device_id={device_id} name={device_name}")
    return device_id, token, pair_code, device_name


async def recv_command(ws, timeout=12.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg_raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - time.monotonic()))
        msg = json.loads(msg_raw)
        if msg.get("type") in ("command", "device.command"):
            return msg
        logger.info(f"Ignoring non-command background message: {msg}")
    raise TimeoutError("Command not received within timeout")


async def run_client_lifecycle(cloud_session: requests.Session, device_id: str, token: str, device_name: str):
    logger.info("=== STEP 5: Connecting Client to Edge Hub via WebSocket ===")
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    async with websockets.connect(EDGE_WS, ssl=ssl_ctx) as ws:
        # Send hello handshake
        await ws.send(json.dumps({
            "type": "hello",
            "device_id": device_id,
            "token": token,
            "client_version": "0.2.0-phase2",
        }))
        welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        assert welcome.get("type") == "welcome", f"Unexpected welcome: {welcome}"
        logger.info(f"Client Handshake Complete: {welcome}")

        # Send heartbeat reporting LOCKED
        await ws.send(json.dumps({
            "type": "heartbeat",
            "state": "LOCKED",
            "app_version": "0.2.0-phase2",
        }))
        hb_ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        assert hb_ack.get("type") == "heartbeat_ack", f"Unexpected heartbeat_ack: {hb_ack}"
        logger.info("Client Heartbeat ACK received.")

        logger.info("=== STEP 6: Verifying Replication to Online Cloud ===")
        # Wait for Edge sync worker to sync this exact device to cloud
        replicated = False
        for attempt in range(20):
            await asyncio.sleep(1.0)
            r_grid = cloud_session.get(f"{CLOUD_BASE}/devices/grid", timeout=10)
            if device_name in r_grid.text or str(device_id) in r_grid.text or device_id[:8] in r_grid.text:
                replicated = True
                logger.info(f"Device {device_name} successfully replicated to Online Cloud Web Dashboard (attempt {attempt+1})!")
                break
        assert replicated, f"Device {device_name} not found in Online Cloud Dashboard after 20s"

        logger.info("=== STEP 7: Testing Remote UNLOCK Command from Cloud ===")
        # Fetch CSRF from cloud devices page
        r_dev = cloud_session.get(f"{CLOUD_BASE}/devices/", timeout=10)
        m = re.search(r'name=["\']csrfmiddlewaretoken["\'] value=["\']([^"\']+)["\']', r_dev.text)
        csrf = m.group(1)

        # Issue remote UNLOCK command from Cloud Web
        r_cmd = cloud_session.post(
            f"{CLOUD_BASE}/devices/{device_id}/action",
            data={"action": "unlock", "csrfmiddlewaretoken": csrf, "next": "cloud_devices"},
            headers={"Referer": f"{CLOUD_BASE}/devices/"},
            timeout=10,
        )
        assert r_cmd.status_code in (200, 302), f"Remote unlock command failed: {r_cmd.status_code}"
        logger.info("Remote UNLOCK command submitted from Cloud Web.")

        # Receive command on Client WS
        cmd_msg = await recv_command(ws)
        logger.info(f"Client received command over WebSocket: {cmd_msg}")
        cmd_payload = cmd_msg.get("command", {})
        assert cmd_payload.get("command_type") == "client.unlock", f"Expected client.unlock, got {cmd_payload}"
        cmd_id = cmd_payload.get("command_id")

        # Client acknowledges execution
        await ws.send(json.dumps({
            "type": "command_ack",
            "command_id": cmd_id,
            "status": "ok",
            "result": {"unlocked": True},
        }))
        # Client updates its state to ONLINE
        await ws.send(json.dumps({
            "type": "state",
            "state": "ONLINE",
        }))
        logger.info("Client executed UNLOCK and sent ACK + state change to Edge Hub.")

        logger.info("=== STEP 8: Testing Remote LOCK Command from Cloud ===")
        # Issue remote LOCK command from Cloud Web
        r_cmd2 = cloud_session.post(
            f"{CLOUD_BASE}/devices/{device_id}/action",
            data={"action": "lock", "csrfmiddlewaretoken": csrf, "next": "cloud_devices"},
            headers={"Referer": f"{CLOUD_BASE}/devices/"},
            timeout=10,
        )
        assert r_cmd2.status_code in (200, 302), f"Remote lock command failed: {r_cmd2.status_code}"
        logger.info("Remote LOCK command submitted from Cloud Web.")

        # Receive command on Client WS
        cmd_msg2 = await recv_command(ws)
        logger.info(f"Client received second command: {cmd_msg2}")
        cmd_payload2 = cmd_msg2.get("command", {})
        assert cmd_payload2.get("command_type") == "client.lock", f"Expected client.lock, got {cmd_payload2}"
        cmd_id2 = cmd_payload2.get("command_id")

        # Client acknowledges execution
        await ws.send(json.dumps({
            "type": "command_ack",
            "command_id": cmd_id2,
            "status": "ok",
            "result": {"locked": True},
        }))
        logger.info("Client executed LOCK and sent ACK.")

        logger.info("=== STEP 9: Testing Remote PING Command from Cloud ===")
        # Issue remote PING command from Cloud Web
        r_cmd3 = cloud_session.post(
            f"{CLOUD_BASE}/devices/{device_id}/action",
            data={"action": "ping", "csrfmiddlewaretoken": csrf, "next": "cloud_devices"},
            headers={"Referer": f"{CLOUD_BASE}/devices/"},
            timeout=10,
        )
        assert r_cmd3.status_code in (200, 302)
        cmd_msg3 = await recv_command(ws)
        assert cmd_msg3.get("command", {}).get("command_type") == "client.ping"
        await ws.send(json.dumps({
            "type": "command_ack",
            "command_id": cmd_msg3["command"]["command_id"],
            "status": "ok",
            "result": {"pong": True},
        }))
        logger.info("Client executed PING and responded.")


def main():
    logger.info("Starting Full Real 3-Tier End-to-End Acceptance Test...")
    check_cloud_health()
    cloud_session = cloud_login()
    verify_cloud_pages(cloud_session)
    device_id, token, _, device_name = register_local_client()
    asyncio.run(run_client_lifecycle(cloud_session, device_id, token, device_name))
    logger.info("============================================================")
    logger.info("SUCCESS: ALL 3 TIERS (CLIENT, LOCAL EDGE, ONLINE CLOUD)")
    logger.info("ARE FULLY CONNECTED AND REMOTE CONTROL VIA WEB WORKS FLAWLESSLY!")
    logger.info("============================================================")


if __name__ == "__main__":
    main()
