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
    forced_ip = os.environ.get("EDGE_PRIMARY_IP")
    if forced_ip:
        return forced_ip

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
    certs_dir = os.environ.get("CERTS")
    candidates = []
    if certs_dir:
        candidates.append(Path(certs_dir) / "edge.fingerprint")
        candidates.append(Path(certs_dir) / "edge.pem")

    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    candidates.append(base_dir / "dev" / "certs" / "edge.fingerprint")
    candidates.append(base_dir / "dev" / "certs" / "edge.pem")

    try:
        from django.conf import settings
        candidates.append(Path(settings.BASE_DIR) / "dev" / "certs" / "edge.fingerprint")
        candidates.append(Path(settings.BASE_DIR) / "dev" / "certs" / "edge.pem")
        candidates.append(Path(settings.BASE_DIR).parent / "dev" / "certs" / "edge.fingerprint")
        candidates.append(Path(settings.BASE_DIR).parent / "dev" / "certs" / "edge.pem")
    except Exception:
        pass

    candidates.append(Path(r"C:\Program Files\GameNet Server\dev\certs\edge.fingerprint"))
    candidates.append(Path(r"C:\Program Files\GameNet Server\dev\certs\edge.pem"))

    for path in candidates:
        if path.exists():
            if path.suffix == ".fingerprint":
                raw = path.read_text().strip().upper()
                clean = raw.replace(":", "").replace(" ", "").replace("-", "")
                if len(clean) == 64:
                    return clean
            elif path.suffix == ".pem":
                try:
                    import hashlib
                    pem = path.read_text()
                    der = ssl.PEM_cert_to_DER_cert(pem)
                    return hashlib.sha256(der).hexdigest().upper()
                except Exception as exc:
                    logger.debug("Failed computing fingerprint from %s: %s", path, exc)

    return ""


def get_interface_pairs() -> list[tuple[str, str]]:
    """Return pairs of (interface_ip, broadcast_ip) for all active interfaces."""
    pairs: list[tuple[str, str]] = []
    seen_ips: set[str] = set()
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and addr.address and not addr.address.startswith("127."):
                    bcast = addr.broadcast or "255.255.255.255"
                    if addr.address not in seen_ips:
                        pairs.append((addr.address, bcast))
                        seen_ips.add(addr.address)
    except Exception:
        pass

    if not pairs:
        # 1. Stdlib gethostbyname_ex: gets all IPv4 addresses on all NICs
        try:
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                if ip and not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in seen_ips:
                    parts = ip.split(".")
                    bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255" if len(parts) == 4 else "255.255.255.255"
                    pairs.append((ip, bcast))
                    seen_ips.add(ip)
        except Exception:
            pass

        # 2. Windows ipconfig fallback
        if os.name == "nt":
            try:
                import subprocess
                out = subprocess.check_output("ipconfig", shell=True, text=True, errors="replace")
                import re
                for m in re.finditer(r"IPv4 Address[ .]*:[ ]*([0-9.]+)", out, re.IGNORECASE):
                    ip = m.group(1).strip()
                    if ip and not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in seen_ips:
                        parts = ip.split(".")
                        bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255" if len(parts) == 4 else "255.255.255.255"
                        pairs.append((ip, bcast))
                        seen_ips.add(ip)
            except Exception:
                pass

        # 3. get_primary_lan_ip fallback
        primary = get_primary_lan_ip()
        if primary and not primary.startswith("127.") and primary not in seen_ips:
            parts = primary.split(".")
            bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255" if len(parts) == 4 else "255.255.255.255"
            pairs.append((primary, bcast))
            seen_ips.add(primary)

    if not pairs:
        pairs = [("127.0.0.1", "255.255.255.255")]
    return pairs


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
        fp = get_certificate_fingerprint()

        # Broadcast periodic beacon every 4 seconds across all active interfaces
        if now - last_beacon_time >= 4.0:
            last_beacon_time = now
            for iface_ip, bcast_ip in get_interface_pairs():
                payload = {
                    "service": "gamenet_salon_server",
                    "name": "سرور بازی سرای رهرو",
                    "host": iface_ip,
                    "port": SERVER_HTTPS_PORT,
                    "fingerprint": fp,
                    "pairing_string": f"{iface_ip}:{SERVER_HTTPS_PORT}#{fp}",
                    "auto_register": True,
                    "timestamp": int(now),
                }
                msg_bytes = json.dumps(payload).encode("utf-8")
                try:
                    sock.sendto(msg_bytes, (bcast_ip, DISCOVERY_UDP_PORT))
                    sock.sendto(msg_bytes, ("255.255.255.255", DISCOVERY_UDP_PORT))
                except Exception as e:
                    logger.debug("Broadcast sendto error on %s: %s", bcast_ip, e)

        # Listen for direct discovery probes from newly started clients
        try:
            data, client_addr = sock.recvfrom(2048)
            try:
                query = json.loads(data.decode("utf-8"))
            except Exception:
                query = {}

            if query.get("query") == "gamenet_discover" or query.get("type") == "discover":
                logger.info("Responding to client discovery query from %s", client_addr)
                # Find matching interface for client
                client_ip = client_addr[0]
                reply_ip = get_primary_lan_ip()
                for iface_ip, _ in get_interface_pairs():
                    # If client and iface share the first two octets, use that interface
                    if ".".join(client_ip.split(".")[:2]) == ".".join(iface_ip.split(".")[:2]):
                        reply_ip = iface_ip
                        break

                reply_payload = {
                    "service": "gamenet_salon_server",
                    "name": "سرور بازی سرای رهرو",
                    "host": reply_ip,
                    "port": SERVER_HTTPS_PORT,
                    "fingerprint": fp,
                    "pairing_string": f"{reply_ip}:{SERVER_HTTPS_PORT}#{fp}",
                    "auto_register": True,
                    "timestamp": int(time.time()),
                }
                sock.sendto(json.dumps(reply_payload).encode("utf-8"), client_addr)
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
