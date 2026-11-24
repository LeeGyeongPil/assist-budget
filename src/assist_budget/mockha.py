"""A fake Home Assistant WebSocket server that runs inside this process.

It speaks the same message shapes as HA 2026.11 ``exposed_entities.py`` for the
four commands assist-budget uses, and records every message it receives so
tests (and the demo) can show exactly what was sent. It is for practice and
tests only: it is the one fake part of ``assist-budget demo``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from types import TracebackType
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

TOKEN = "mock-token"  # the mock accepts only this token


class MockHA:
    """Start with ``with MockHA(exposed) as ha:`` and connect to ``ha.url``."""

    def __init__(self, exposed: Iterable[str], version: str = "2026.11.3", token: str = TOKEN) -> None:
        self.exposed: set[str] = set(exposed)
        self.version = version
        self.token = token
        self.received: list[dict[str, Any]] = []  # every message after authentication
        self.lock = threading.Lock()
        self._server: Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        assert self._server is not None, "start the mock first"
        host, port = self._server.socket.getsockname()[:2]
        return f"ws://{host}:{port}/api/websocket"

    @property
    def write_commands(self) -> list[dict[str, Any]]:
        """Messages that change HA state (everything except reads)."""
        return [m for m in self.received if m.get("type") == "homeassistant/expose_entity"]

    def __enter__(self) -> MockHA:
        self._server = serve(self._handle, "127.0.0.1", 0)  # port 0: any free port, loopback only
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # -- protocol ----------------------------------------------------------
    def _handle(self, conn: ServerConnection) -> None:
        try:
            conn.send(json.dumps({"type": "auth_required", "ha_version": self.version}))
            auth = json.loads(conn.recv())
            if auth.get("type") != "auth" or auth.get("access_token") != self.token:
                conn.send(json.dumps({"type": "auth_invalid", "message": "Invalid access token or password"}))
                return
            conn.send(json.dumps({"type": "auth_ok", "ha_version": self.version}))
            for raw in conn:
                message = json.loads(raw)
                with self.lock:
                    self.received.append(message)
                    reply = self._dispatch(message)
                conn.send(json.dumps(reply))
        except ConnectionClosed:
            pass

    def _dispatch(self, message: dict[str, Any]) -> dict[str, Any]:
        kind, msg_id = message.get("type"), message.get("id")
        if kind == "get_config":
            return self._ok(msg_id, {"version": self.version, "location_name": "Mock Home"})
        if kind == "homeassistant/expose_entity/list":
            listing = {eid: {"conversation": True} for eid in sorted(self.exposed)}
            return self._ok(msg_id, {"exposed_entities": listing})
        if kind == "homeassistant/expose_entity":
            ids, flag = message.get("entity_ids"), message.get("should_expose")
            if (not isinstance(ids, list) or not isinstance(flag, bool)
                    or message.get("assistants") != ["conversation"]):
                return self._error(msg_id, "invalid_format", "invalid expose_entity message")
            changed = []
            for eid in ids:
                if (eid in self.exposed) != flag:
                    changed.append(eid)
                (self.exposed.add if flag else self.exposed.discard)(eid)
            return self._ok(msg_id, {"changed_entity_ids": changed})
        return self._error(msg_id, "unknown_command", f"Unknown command {kind}")

    @staticmethod
    def _ok(msg_id: Any, result: Any) -> dict[str, Any]:
        return {"id": msg_id, "type": "result", "success": True, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: str, text: str) -> dict[str, Any]:
        return {"id": msg_id, "type": "result", "success": False, "error": {"code": code, "message": text}}
