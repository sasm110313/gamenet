"""Wake-on-LAN (WoL) utilities for gaming stations on the salon LAN."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from django.db import transaction

from apps.core.roles import require_edge

logger = logging.getLogger("gamenet.devices.wol")

_MAC_HEX_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
_ARP_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")
_LINUX_ADDR_RE = re.compile(r"inet\s+(\d+\.\d+\.\d+\.\d+/\d+)(?:.*?brd\s+(\d+\.\d+\.\d+\.\d+))?")


class WolError(ValueError):
    """Raised when a Wake-on-LAN operation cannot be performed."""


def normalize_mac(raw: str | None) -> str:
    """Validate and normalize a MAC address to AA:BB:CC:DD:EE:FF."""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    compact = re.sub(r"[:\-.\s]", "", text)
    if not _MAC_HEX_RE.fullmatch(compact):
        raise WolError("فرمت آدرس MAC نامعتبر است (مثال صحیح: AA:BB:CC:DD:EE:FF).")
    upper = compact.upper()
    if upper in {"000000000000", "FFFFFFFFFFFF"}:
        raise WolError("آدرس MAC واردشده معتبر نیست.")
    return ":".join(upper[i : i + 2] for i in range(0, 12, 2))


def normalize_mac_safe(raw: str | None) -> str:
    """Return normalized MAC or empty string if invalid."""
    try:
        return normalize_mac(raw)
    except WolError:
        return ""


def build_magic_packet(mac: str) -> bytes:
    """Construct a standard 102-byte AMD/IEEE Wake-on-LAN Magic Packet."""
    clean = normalize_mac(mac)
    if not clean:
        raise WolError("آدرس MAC برای ساخت بسته Wake-on-LAN الزامی است.")
    mac_bytes = bytes.fromhex(clean.replace(":", ""))
    return b"\xff" * 6 + mac_bytes * 16


def _valid_lan_ipv4(ip_str: str | None) -> ipaddress.IPv4Address | None:
    if not ip_str:
        return None
    try:
        ip = ipaddress.IPv4Address(str(ip_str).strip())
    except ipaddress.AddressValueError:
        return None
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        return None
    return ip


def is_lan_host_reachable(ip_address: str | None) -> bool:
    """Fast non-blocking check whether a salon LAN PC appears powered ON even if client WS is offline."""
    target_ip = _valid_lan_ipv4(ip_address)
    if target_ip is None:
        return False
    ip_text = str(target_ip)

    # 1. Fast single-packet ICMP ping
    try:
        cmd = (
            ["ping", "-n", "1", "-w", "600", ip_text]
            if sys.platform == "win32"
            else ["ping", "-c", "1", "-W", "1", ip_text]
        )
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5, check=False)
        if proc.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass

    # 2. Active neighbor state check on Linux
    if sys.platform != "win32":
        try:
            proc = subprocess.run(
                ["ip", "-4", "neigh", "show", ip_text],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            out = (proc.stdout or "").upper()
            if any(state in out for state in ("REACHABLE", "DELAY", "PROBE")):
                return True
        except (OSError, subprocess.SubprocessError):
            pass

    # 3. Quick TCP SYN check on Windows RPC/SMB ports; ConnectionRefused proves host IP stack is ON
    for port in (445, 135):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.35)
        try:
            sock.connect((ip_text, port))
            return True
        except ConnectionRefusedError:
            return True
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass

    return False


def resolve_mac_from_arp(ip_address: str | None) -> str:
    """Passively look up a client MAC address from the OS ARP/neighbor cache."""
    target_ip = _valid_lan_ipv4(ip_address)
    if target_ip is None:
        return ""
    ip_text = str(target_ip)

    # 1. Linux procfs ARP table (zero subprocess overhead)
    proc_arp = Path("/proc/net/arp")
    if proc_arp.is_file():
        try:
            lines = proc_arp.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]
            for line in lines:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip_text and parts[2] != "0x0":
                    mac = normalize_mac_safe(parts[3])
                    if mac:
                        return mac
        except OSError:
            pass

    # 2. Linux `ip neigh` fallback
    if sys.platform != "win32":
        try:
            proc = subprocess.run(
                ["ip", "-4", "neigh", "show", ip_text],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                m = _ARP_MAC_RE.search(proc.stdout)
                if m:
                    return normalize_mac_safe(m.group(0))
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        # 3. Windows `arp -a <ip>`
        try:
            proc = subprocess.run(
                ["arp", "-a", ip_text],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if proc.stdout:
                for line in proc.stdout.splitlines():
                    if ip_text in line:
                        m = _ARP_MAC_RE.search(line)
                        if m:
                            return normalize_mac_safe(m.group(0))
        except (OSError, subprocess.SubprocessError):
            pass

    return ""


def _local_ipv4_interfaces() -> list[tuple[str, ipaddress.IPv4Network, str]]:
    """Return [(iface_ip, network, broadcast_ip)] for active non-loopback LAN NICs."""
    results: list[tuple[str, ipaddress.IPv4Network, str]] = []
    seen_ips: set[str] = set()

    if sys.platform != "win32":
        try:
            proc = subprocess.run(
                ["ip", "-4", "-o", "addr", "show"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    m = _LINUX_ADDR_RE.search(line)
                    if not m:
                        continue
                    try:
                        iface = ipaddress.IPv4Interface(m.group(1))
                    except ipaddress.AddressValueError:
                        continue
                    if (
                        iface.ip.is_loopback
                        or iface.ip.is_link_local
                        or iface.network.prefixlen >= 31
                    ):
                        continue
                    ip_str = str(iface.ip)
                    if ip_str in seen_ips:
                        continue
                    seen_ips.add(ip_str)
                    brd = m.group(2) or str(iface.network.broadcast_address)
                    results.append((ip_str, iface.network, brd))
        except (OSError, subprocess.SubprocessError):
            pass

    if not results:
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip_str = info[4][0]
                try:
                    addr = ipaddress.IPv4Address(ip_str)
                except ipaddress.AddressValueError:
                    continue
                if addr.is_loopback or addr.is_link_local or ip_str in seen_ips:
                    continue
                seen_ips.add(ip_str)
                net = ipaddress.IPv4Network(f"{ip_str}/24", strict=False)
                results.append((ip_str, net, str(net.broadcast_address)))
        except OSError:
            pass

    return results


def send_wol_magic_packet(
    mac: str,
    *,
    ip_hint: str | None = None,
    ports: tuple[int, ...] = (9, 7),
) -> dict[str, Any]:
    """Broadcast a Wake-on-LAN Magic Packet on relevant Edge LAN interfaces."""
    clean_mac = normalize_mac(mac)
    if not clean_mac:
        raise WolError("آدرس MAC برای روشن کردن دستگاه ثبت نشده است.")

    packet = build_magic_packet(clean_mac)
    hint_ip = _valid_lan_ipv4(ip_hint)
    ifaces = _local_ipv4_interfaces()

    # Ordered (bind_ip_or_none, dest_broadcast_ip) pairs
    candidates: list[tuple[str | None, str]] = []
    seen_pairs: set[tuple[str | None, str]] = set()

    def _add(bind_ip: str | None, dest_ip: str) -> None:
        key = (bind_ip, dest_ip)
        if key not in seen_pairs:
            seen_pairs.add(key)
            candidates.append(key)

    # 1. Prioritize interface matching device's last known LAN subnet
    matched_hint_iface = False
    if hint_ip is not None:
        for iface_ip, net, brd in ifaces:
            if hint_ip in net:
                matched_hint_iface = True
                _add(iface_ip, brd)
                _add(iface_ip, "255.255.255.255")
        if not matched_hint_iface:
            fallback_brd = str(ipaddress.IPv4Network(f"{hint_ip}/24", strict=False).broadcast_address)
            _add(None, fallback_brd)

    # 2. All other LAN interfaces + global limited broadcast
    for iface_ip, _net, brd in ifaces:
        _add(iface_ip, brd)
        _add(iface_ip, "255.255.255.255")
    _add(None, "255.255.255.255")

    sent_targets: list[str] = []
    last_error: OSError | None = None

    for bind_ip, dest_ip in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if bind_ip:
                sock.bind((bind_ip, 0))
            for port in ports:
                sock.sendto(packet, (dest_ip, port))
                sent_targets.append(f"{dest_ip}:{port}")
        except OSError as exc:
            last_error = exc
            logger.debug("WoL send error via %s -> %s: %s", bind_ip or "default", dest_ip, exc)
        finally:
            sock.close()

    if not sent_targets:
        detail = str(last_error) if last_error else "خطای شبکه محلی"
        raise WolError(f"ارسال بسته Wake-on-LAN ناموفق بود: {detail}")

    logger.info(
        "Sent Wake-on-LAN Magic Packet to MAC=%s targets=%s",
        clean_mac,
        ",".join(sent_targets[:6]),
    )
    return {
        "mac": clean_mac,
        "packet_bytes": len(packet),
        "targets": sent_targets,
    }


def sync_device_mac(
    device,
    *,
    explicit_mac: str = "",
    ip_address: str | None = None,
    emit_sync: bool = True,
) -> str:
    """Resolve and persist MAC address in device.metadata, emitting sync if changed."""
    require_edge()
    meta = dict(device.metadata or {})
    existing_mac = normalize_mac_safe(meta.get("mac_address"))
    candidate = normalize_mac_safe(explicit_mac)
    if not candidate and not existing_mac:
        candidate = resolve_mac_from_arp(ip_address or device.ip_address)

    if candidate and candidate != existing_mac:
        meta["mac_address"] = candidate
        device.metadata = meta
        with transaction.atomic():
            device.save(update_fields=["metadata", "updated_at"])
            if emit_sync:
                from apps.synchronization.events import emit

                emit(
                    "device.updated",
                    aggregate_type="device",
                    aggregate_id=str(device.id),
                    payload={
                        "device_id": str(device.id),
                        "name": device.name,
                        "metadata": device.metadata,
                        "is_active": device.is_active,
                    },
                )
        return candidate

    return existing_mac
