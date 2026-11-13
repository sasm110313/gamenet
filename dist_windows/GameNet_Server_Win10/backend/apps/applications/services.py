from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from typing import Any
from django.conf import settings

DEFAULT_GAMES = [
    {
        "id": "r6s",
        "name": "Rainbow Six Siege (رهرو)",
        "category": "شوتر تاکتیکال",
        "icon": "🛡️",
        "executable": r"c:\program files(x86)\games\rainbow six siege\rainbowsix_rahro_native.exe",
        "arguments": "",
        "working_dir": r"c:\program files(x86)\games\rainbow six siege",
        "color": "border-sky-500/30 bg-sky-500/[0.06]",
        "is_active": True,
    },
    {
        "id": "cs16",
        "name": "Counter-Strike 1.6",
        "category": "شوتر کلاسیک",
        "icon": "🎯",
        "executable": r"c:\program files(x86)\games\counter-strike 1.6\hl.exe",
        "arguments": "-game cstrike",
        "working_dir": r"c:\program files(x86)\games\counter-strike 1.6",
        "color": "border-amber/30 bg-amber/[0.06]",
        "is_active": True,
    },
]


def _catalog_path() -> str:
    # 1. Dedicated env var if set
    env_dir = os.environ.get("GAMENET_DATA_DIR")
    if env_dir:
        try:
            os.makedirs(env_dir, exist_ok=True)
            return os.path.join(env_dir, "games_catalog.json")
        except OSError:
            pass

    # 2. Systemd runtime dir (/opt/gamenet/backend/.runtime) or BASE_DIR/.runtime
    base_dir = getattr(settings, "BASE_DIR", os.getcwd())
    candidates = [
        os.path.join(base_dir, ".runtime"),
        os.path.join(base_dir, "data"),
        "/opt/gamenet/backend/.runtime",
        os.path.join(tempfile.gettempdir(), "gamenet_data"),
    ]

    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            test_file = os.path.join(candidate, ".perm_test")
            with open(test_file, "w") as f:
                f.write("1")
            os.remove(test_file)
            return os.path.join(candidate, "games_catalog.json")
        except OSError:
            continue

    return os.path.join(tempfile.gettempdir(), "games_catalog.json")


def _clean_path_field(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and (
        (text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'")
    ):
        text = text[1:-1].strip()
    return text


def _meta_path() -> str:
    return f"{_catalog_path()}.meta.json"


def _games_hash(games: list[dict[str, Any]]) -> str:
    raw = json.dumps(games, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _read_meta() -> dict[str, Any]:
    meta_file = _meta_path()
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    cat_path = _catalog_path()
    try:
        mtime_ms = int(os.path.getmtime(cat_path) * 1000) if os.path.exists(cat_path) else 0
    except OSError:
        mtime_ms = 0
    return {"version": mtime_ms}


def _write_meta(version: int, content_hash: str) -> None:
    meta_file = _meta_path()
    tmp_path = f"{meta_file}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"version": int(version), "hash": content_hash}, f, ensure_ascii=False)
        os.replace(tmp_path, meta_file)
    except OSError:
        pass


def get_games_catalog() -> list[dict[str, Any]]:
    path = _catalog_path()
    if not os.path.exists(path):
        save_games_catalog(DEFAULT_GAMES, version=0)
        return list(DEFAULT_GAMES)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return list(DEFAULT_GAMES)


def get_games_catalog_state() -> dict[str, Any]:
    games = get_games_catalog()
    meta = _read_meta()
    return {
        "games": games,
        "version": int(meta.get("version") or 0),
        "hash": _games_hash(games),
    }


def save_games_catalog(games: list[dict[str, Any]], *, version: int | None = None) -> None:
    path = _catalog_path()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(games, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    ver = int(time.time() * 1000) if version is None else int(version)
    _write_meta(ver, _games_hash(games))

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                "gamenet_all_devices",
                {"type": "device.games_updated"},
            )
    except Exception:
        pass

    role = os.environ.get("GAMENET_ROLE", "edge")
    if role == "edge":
        try:
            import threading

            def _push_games_to_cloud():
                try:
                    from apps.synchronization.cloud_client import CloudClient
                    from apps.synchronization.edge_credentials import is_registered, load_credentials
                    from apps.synchronization.edge_runtime import send_heartbeat

                    if is_registered():
                        creds = load_credentials()
                        client = CloudClient(creds)
                        send_heartbeat(client)
                except Exception:
                    pass

            threading.Thread(target=_push_games_to_cloud, daemon=True).start()
        except Exception:
            pass
    elif role == "cloud":
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            from apps.synchronization.models import EdgeNode

            channel_layer = get_channel_layer()
            if channel_layer:
                for edge in EdgeNode.objects.filter(is_active=True):
                    async_to_sync(channel_layer.group_send)(
                        f"edge_{edge.id.hex}",
                        {
                            "type": "edge.games_pushed",
                            "games_catalog": games,
                            "games_version": ver,
                            "games_hash": _games_hash(games),
                        },
                    )
        except Exception:
            pass


def add_game(
    name: str,
    category: str,
    icon: str = "🎮",
    executable: str = "",
    arguments: str = "",
    working_dir: str = "",
    color: str = "",
    is_active: bool = True,
) -> dict[str, Any]:
    catalog = get_games_catalog()
    game_id = "game_" + uuid.uuid4().hex[:8]
    item = {
        "id": game_id,
        "name": name.strip(),
        "category": category.strip() or "بازی",
        "icon": icon.strip() or "🎮",
        "executable": _clean_path_field(executable),
        "arguments": arguments.strip(),
        "working_dir": _clean_path_field(working_dir),
        "color": color.strip() or "border-neon/30 bg-neon/[0.06]",
        "is_active": bool(is_active),
    }
    catalog.append(item)
    save_games_catalog(catalog)
    return item


def update_game(
    game_id: str,
    name: str,
    category: str,
    icon: str = "🎮",
    executable: str = "",
    arguments: str = "",
    working_dir: str = "",
    color: str = "",
    is_active: bool = True,
) -> dict[str, Any] | None:
    catalog = get_games_catalog()
    for i, g in enumerate(catalog):
        if g.get("id") == game_id:
            catalog[i] = {
                "id": game_id,
                "name": name.strip(),
                "category": category.strip() or "بازی",
                "icon": icon.strip() or "🎮",
                "executable": _clean_path_field(executable),
                "arguments": arguments.strip(),
                "working_dir": _clean_path_field(working_dir),
                "color": color.strip() or g.get("color", "border-neon/30 bg-neon/[0.06]"),
                "is_active": bool(is_active),
            }
            save_games_catalog(catalog)
            return catalog[i]
    return None


def delete_game(game_id: str) -> bool:
    catalog = get_games_catalog()
    initial_len = len(catalog)
    catalog = [g for g in catalog if g.get("id") != game_id]
    if len(catalog) != initial_len:
        save_games_catalog(catalog)
        return True
    return False


def reset_games_catalog() -> list[dict[str, Any]]:
    save_games_catalog(DEFAULT_GAMES)
    return list(DEFAULT_GAMES)
