#!/usr/bin/env python3
"""Persistent live gaming client connecting to the local edge hub."""

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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gamenet.live_client")

EDGE_BASE = "https://127.0.0.1:19443"
EDGE_WS = "wss://127.0.0.1:19443/ws/device/"
CLIENT_NAME = os.environ.get("CLIENT_NAME", "PC-01")


def get_or_register_client() -> tuple[str, str]:
    # Check if client device exists in local edge DB
    cmd = [
        "backend/.venv/bin/python",
        "-c",
        f"""
import os, sys, django
sys.path.insert(0, 'backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamenet.settings.edge')
django.setup()
from apps.clients.models import ClientDevice
d = ClientDevice.objects.filter(name='{CLIENT_NAME}', is_active=True).first()
if d:
    print('EXISTS:' + str(d.id))
else:
    print('NONE')
""",
    ]
    out = subprocess.check_output(cmd, text=True)
    if "EXISTS:" in out:
        # Re-register or create a new pairing code to get a fresh token
        logger.info(f"Device {CLIENT_NAME} already exists in DB, getting fresh pairing code...")
    
    cmd_code = [
        "backend/.venv/bin/python",
        "-c",
        f"""
import os, sys, django
sys.path.insert(0, 'backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamenet.settings.edge')
django.setup()
from apps.devices.services import create_registration_code
from apps.clients.models import ClientDevice
# remove old inactive test device if needed
ClientDevice.objects.filter(name='{CLIENT_NAME}').delete()
reg = create_registration_code(label='{CLIENT_NAME}')
print('PAIR_CODE:' + reg.code)
""",
    ]
    out_code = subprocess.check_output(cmd_code, text=True)
    m = re.search(r"PAIR_CODE:([A-Z0-9]+)", out_code)
    pair_code = m.group(1)

    payload = {
        "code": pair_code,
        "name": CLIENT_NAME,
        "hostname": f"WIN7-{CLIENT_NAME}",
        "operating_system": "Windows 7 SP1 (64-bit)",
        "application_version": "0.2.0-phase2",
        "mac_address": "00:1A:2B:3C:4D:99",
    }
    r = requests.post(f"{EDGE_BASE}/api/v1/device/register", json=payload, verify=False, timeout=10)
    assert r.status_code == 201, f"Registration failed: {r.status_code} {r.text}"
    data = r.json()
    logger.info(f"Registered {CLIENT_NAME}: device_id={data['device_id']}")
    return data["device_id"], data["token"]


async def main():
    device_id, token = get_or_register_client()
    logger.info(f"Starting live WebSocket connection for {CLIENT_NAME}...")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    current_state = "LOCKED"

    while True:
        try:
            async with websockets.connect(EDGE_WS, ssl=ssl_ctx) as ws:
                # 1. Handshake
                await ws.send(json.dumps({
                    "type": "hello",
                    "device_id": device_id,
                    "token": token,
                    "client_version": "0.2.0-phase2",
                }))
                welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
                logger.info(f"Connected to Edge Hub: {welcome.get('hub_name')} | Desired: {welcome.get('desired_state')}")

                # 2. Initial Heartbeat
                await ws.send(json.dumps({
                    "type": "heartbeat",
                    "state": current_state,
                    "app_version": "0.2.0-phase2",
                }))

                async def heartbeat_loop():
                    while True:
                        await asyncio.sleep(5.0)
                        try:
                            await ws.send(json.dumps({
                                "type": "heartbeat",
                                "state": current_state,
                                "app_version": "0.2.0-phase2",
                            }))
                            logger.debug("Sent heartbeat")
                        except Exception:
                            break

                hb_task = asyncio.create_task(heartbeat_loop())

                try:
                    while True:
                        msg_raw = await ws.recv()
                        msg = json.loads(msg_raw)
                        kind = msg.get("type")

                        if kind in ("command", "device.command"):
                            cmd = msg.get("command", {})
                            cmd_type = cmd.get("command_type")
                            cmd_id = cmd.get("command_id")
                            logger.info(f">>> RECEIVED REMOTE COMMAND: {cmd_type} (id={cmd_id})")

                            if cmd_type == "client.unlock":
                                current_state = "ONLINE"
                                await ws.send(json.dumps({
                                    "type": "command_ack",
                                    "command_id": cmd_id,
                                    "status": "ok",
                                    "result": {"unlocked": True},
                                }))
                                await ws.send(json.dumps({"type": "state", "state": "ONLINE"}))
                                logger.info(f"[{CLIENT_NAME}] UNLOCKED! State is now ONLINE.")

                            elif cmd_type == "client.lock":
                                current_state = "LOCKED"
                                await ws.send(json.dumps({
                                    "type": "command_ack",
                                    "command_id": cmd_id,
                                    "status": "ok",
                                    "result": {"locked": True},
                                }))
                                await ws.send(json.dumps({"type": "state", "state": "LOCKED"}))
                                logger.info(f"[{CLIENT_NAME}] LOCKED! Screen locked.")

                            elif cmd_type == "client.ping":
                                await ws.send(json.dumps({
                                    "type": "command_ack",
                                    "command_id": cmd_id,
                                    "status": "ok",
                                    "result": {"pong": True, "time": time.time()},
                                }))
                                logger.info(f"[{CLIENT_NAME}] PONG sent.")

                            elif cmd_type == "client.restart":
                                await ws.send(json.dumps({
                                    "type": "command_ack",
                                    "command_id": cmd_id,
                                    "status": "ok",
                                    "result": {"restarting": True},
                                }))
                                logger.info(f"[{CLIENT_NAME}] Restart acknowledged.")

                        elif kind == "heartbeat_ack":
                            logger.debug("Received heartbeat ACK")

                        elif kind == "state_ack":
                            logger.debug(f"State acknowledged: {msg.get('state')}")

                finally:
                    hb_task.cancel()

        except Exception as exc:
            logger.warning(f"Connection lost ({exc}). Reconnecting in 3s...")
            await asyncio.sleep(3.0)


if __name__ == "__main__":
    asyncio.run(main())
