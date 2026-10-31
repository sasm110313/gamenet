"""HTTP client the edge uses to talk to the cloud.

Every call is authenticated with the edge bearer credential over TLS. The edge
never accepts inbound connections from the cloud.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from django.conf import settings

from apps.synchronization.edge_credentials import EdgeCredentials

logger = logging.getLogger("gamenet.cloud_client")


class CloudUnavailable(RuntimeError):
    pass


class CloudRejected(RuntimeError):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f"cloud rejected request: HTTP {status} {body}")


class CloudClient:
    def __init__(self, creds: EdgeCredentials, *, timeout: int | None = None):
        self.creds = creds
        self.base = creds.base_url.rstrip("/")
        self.timeout = timeout or settings.EDGE_REQUEST_TIMEOUT_SECONDS
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Edge {creds.edge_id}.{creds.secret}",
                "Accept": "application/json",
                "User-Agent": f"gamenet-edge/{settings.GAMENET_VERSION}",
            }
        )
        self.verify: str | bool = settings.CLOUD_CA_BUNDLE or True

    # -- low level ---------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base}{path}"
        try:
            resp = self.session.request(method, url, timeout=self.timeout, verify=self.verify, **kwargs)
        except requests.RequestException as exc:
            raise CloudUnavailable(str(exc)) from exc
        if resp.status_code >= 500:
            raise CloudUnavailable(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text[:500]
            raise CloudRejected(resp.status_code, body)
        if resp.status_code == 204:
            return {}
        return resp.json()

    # -- protocol ----------------------------------------------------------
    @classmethod
    def register(cls, *, base_url: str, code: str, name: str, software_version: str,
                 ca_bundle: str = "") -> dict:
        session = requests.Session()
        payload = {"code": code, "name": name, "software_version": software_version}
        try:
            resp = session.post(
                f"{base_url.rstrip('/')}/api/v1/edge/register",
                json=payload,
                timeout=15,
                verify=ca_bundle or True,
            )
        except requests.RequestException as exc:
            raise CloudUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            raise CloudRejected(resp.status_code, resp.text[:500])
        return resp.json()

    def heartbeat(self, payload: dict) -> dict:
        return self._request("POST", "/api/v1/edge/heartbeat", json=payload)

    def post_events(self, events: list[dict]) -> dict:
        return self._request("POST", "/api/v1/edge/events:batch", json={"events": events})

    def fetch_commands(self, *, limit: int = 50) -> dict:
        return self._request("GET", "/api/v1/edge/commands/pending", params={"limit": limit})

    def fetch_config(self, *, after: int = 0) -> dict:
        return self._request("GET", "/api/v1/edge/config", params={"after": after})

    def ack_command(self, command_id: str, *, status: str, result: Any = None,
                    error: str = "") -> dict:
        return self._request(
            "POST",
            f"/api/v1/edge/commands/{command_id}/ack",
            json={"status": status, "result": result, "error": error},
        )
