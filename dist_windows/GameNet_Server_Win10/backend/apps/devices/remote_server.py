"""RDP helpers for the hub (salon server) machine itself.

The hub usually runs as a Windows service, so a browser cannot launch ``mstsc``
inside the operator's session. This module exposes the practical pieces:

* read whether Remote Desktop is enabled;
* enable it (registry + firewall rule + TermService);
* build a ready-to-use ``.rdp`` file for the hub's LAN address.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger("gamenet.rdp")

RDP_PORT = 3389
_TS_KEY = r"SYSTEM\CurrentControlSet\Control\Terminal Server"
_FIREWALL_RULE = "GameNet Server RDP"


def is_windows() -> bool:
    return sys.platform == "win32"


def rdp_status() -> dict:
    """Return {supported, enabled, port} without ever raising."""
    info = {"supported": is_windows(), "enabled": None, "port": RDP_PORT}
    if not is_windows():
        return info
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _TS_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "fDenyTSConnections")
        info["enabled"] = int(value) == 0
    except Exception as exc:
        logger.warning("Could not read RDP state: %s", exc)
    return info


def enable_rdp() -> tuple[bool, str]:
    """Enable Remote Desktop + firewall + service. Returns (ok, message)."""
    if not is_windows():
        return False, "این قابلیت فقط روی ویندوز در دسترس است."
    steps: list[str] = []
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, _TS_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "fDenyTSConnections", 0, winreg.REG_DWORD, 0)
        steps.append("RDP فعال شد")
    except Exception as exc:
        return False, f"تغییر رجیستری ناموفق بود: {exc}"

    try:
        subprocess.run(
            ["sc", "config", "TermService", "start=", "auto"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        subprocess.run(["net", "start", "TermService"], capture_output=True, timeout=15, check=False)
        steps.append("سرویس TermService")
    except Exception:
        pass

    try:
        # Locale-independent rule (the built-in rule group name is localized).
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={_FIREWALL_RULE}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={_FIREWALL_RULE}",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={RDP_PORT}",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        steps.append("پورت 3389 در فایروال")
    except Exception:
        pass

    return True, "، ".join(steps) + " آماده شد."


def build_rdp_file(host: str, username: str = "") -> str:
    """A minimal .rdp file that works from any Windows client."""
    address = (host or "127.0.0.1").strip()
    lines = [
        f"full address:s:{address}:{RDP_PORT}",
        f"username:s:{username}",
        "prompt for credentials:i:1",
        "authentication level:i:2",
        "screen mode id:i:2",
        "use multimon:i:1",
        "redirectclipboard:i:1",
        "redirectprinters:i:0",
        "audiomode:i:0",
        "session bpp:i:32",
        "compression:i:1",
        "networkautodetect:i:1",
    ]
    return "\r\n".join(lines) + "\r\n"
