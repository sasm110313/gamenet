"""LAN Auto-Discovery service for GameNet Salon Server.

Listens on and broadcasts to UDP port 19445 on the local subnet so clients
(PCs in the gaming salon) automatically discover the server's IP address and
certificate fingerprint upon booting, exactly like SmartLaunch.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import ssl
import threading
import time
from pathlib import Path

logger = logging.getLogger("gamenet.devices.discovery")

DISCOVERY_UDP_PORT = int(os.environ.get("EDGE_DISCOVERY_PORT", 19445))
SERVER_HTTPS_PORT = int(os.environ.get("EDGE_LAN_PORT", 19443))
_started = False
_lock = threading.Lock()


def get_primary_lan_ip() -> str:
    """Detect the active primary LAN IP address on this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Does not send actual traffic, just routes to determine interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def get_certificate_fingerprint() -> str:
    """Return the SHA-256 fingerprint of the salon server certificate."""
    # 1. Check edge.fingerprint file
    certs_dir = os.environ.get("CERTS")
    candidates = []
    if certs_dir:
        candidates.append(Path(certs_dir) / "edge.fingerprint")
        candidates.append(Path(certs_dir) / "edge.pem")
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    candidates.append(base_dir / "dev" / "certs" / "edge.fingerprint")
    candidates.append(base_dir / "dev" / "certs" / "edge.pem")

    for path in candidates:
        if path.exists():
            if path.suffix == ".fingerprint":
                fp = path.read_text().strip().upper()
                if len(fp) == 64:
                    return fp
            elif path.suffix == ".pem":
                try:
                    import hashlib
                    pem = path.read_text()
                    der = ssl.PEM_cert_to_DER_cert(pem)
                    return hashlib.sha256(der).hexdigest().upper()
                except Exception as exc:
                    logger.debug("Failed computing fingerprint from %s: %s", path, exc)

    return ""


def _discovery_loop():
    logger.info("Starting GameNet LAN auto-discovery daemon on UDP port %s...", DISCOVERY_UDP_PORT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    try:
        sock.bind(("0.0.0.0", DISCOVERY_UDP_PORT))
    except Exception as exc:
        logger.error("Failed to bind UDP discovery socket on port %s: %s", DISCOVERY_UDP_PORT, exc)
        return

    sock.settimeout(2.0)
    last_beacon_time = 0.0

    while True:
        now = time.time()
        primary_ip = get_primary_lan_ip()
        fp = get_certificate_fingerprint()

        payload = {
            "service": "gamenet_salon_server",
            "name": "سرور سالن گیم‌نت",
            "host": primary_ip,
            "port": SERVER_HTTPS_PORT,
            "fingerprint": fp,
            "pairing_string": f"https://{primary_ip}:{SERVER_HTTPS_PORT}#{fp}",
            "auto_register": True,
            "timestamp": int(now),
        }
        msg_bytes = json.dumps(payload).encode("utf-8")

        # Broadcast periodic beacon every 4 seconds
        if now - last_beacon_time >= 4.0:
            last_beacon_time = now
            try:
                sock.sendto(msg_bytes, ("255.255.255.255", DISCOVERY_UDP_PORT))
            except Exception as e:
                logger.debug("Broadcast sendto error: %s", e)

        # Listen for direct discovery probes from newly started clients
        try:
            data, client_addr = sock.recvfrom(2048)
            try:
                query = json.loads(data.decode("utf-8"))
            except Exception:
                query = {}

            if query.get("query") == "gamenet_discover" or query.get("type") == "discover":
                logger.info("Responding to client discovery query from %s", client_addr)
                sock.sendto(msg_bytes, client_addr)
        except socket.timeout:
            continue
        except Exception as exc:
            logger.debug("UDP recv error: %s", exc)
            time.sleep(1)


def start_discovery_service():
    """Ensure discovery thread is running in the background."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
        t = threading.Thread(target=_discovery_loop, name="gamenet_lan_discovery", daemon=True)
        t.start()
