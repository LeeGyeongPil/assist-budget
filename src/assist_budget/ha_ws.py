"""A minimal Home Assistant WebSocket client (authentication, get_config, expose commands).

The ``homeassistant/expose_entity`` commands are what the HA frontend uses for
its "Voice assistants" page. They are not in the public API documentation, so
``apply`` checks the HA version first (see ``apply.py``).
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from . import EXIT_CONNECTION
from .errors import AssistBudgetError

ASSISTANT = "conversation"
CONNECT_TIMEOUT = 10.0
REPLY_TIMEOUT = 60.0  # a busy HA can be slow; slow is not an error


def validate_url(url: str) -> str:
    """Accept only ``ws://`` / ``wss://`` URLs (HA's address ends in /api/websocket)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss") or not parsed.netloc:
        raise AssistBudgetError("err_bad_url", url=url)
    return url


class HAClient:
    """One authenticated WebSocket session. Use as a context manager so it always closes."""

    def __init__(self, url: str, token: str) -> None:
        self._url = validate_url(url)
        self._token = token
        self._ws: ClientConnection | None = None
        self._stack = ExitStack()
        self._next_id = 0
        self.ha_version: str | None = None

    def __enter__(self) -> HAClient:
        try:
            # websockets 17 wants connect() entered as a context manager; the stack closes it in close()
            self._ws = self._stack.enter_context(
                connect(self._url, open_timeout=CONNECT_TIMEOUT, max_size=16 * 1024 * 1024))
            first = self._recv()
            if first.get("type") != "auth_required":
                raise AssistBudgetError("err_ws_protocol", EXIT_CONNECTION, url=self._url)
            self._ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            reply = self._recv()
        except (OSError, WebSocketException, TimeoutError) as exc:
            self.close()
            raise AssistBudgetError("err_connect", EXIT_CONNECTION, url=self._url, reason=str(exc) or type(exc).__name__) from exc
        except AssistBudgetError:
            self.close()
            raise
        if reply.get("type") != "auth_ok":
            self.close()
            raise AssistBudgetError("err_auth", EXIT_CONNECTION, url=self._url)
        self.ha_version = reply.get("ha_version")
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()

    def close(self) -> None:
        """Close the socket (safe to call twice)."""
        try:
            self._stack.close()
        except (OSError, WebSocketException):
            pass
        self._ws = None

    def _recv(self) -> dict[str, Any]:
        assert self._ws is not None
        data = self._ws.recv(timeout=REPLY_TIMEOUT)
        return json.loads(data)

    def call(self, command: str, **payload: Any) -> Any:
        """Send one command and return its ``result``; raises exit code 4 on failure."""
        if self._ws is None:
            raise AssistBudgetError("err_ws_closed", EXIT_CONNECTION)
        self._next_id += 1
        message = {"id": self._next_id, "type": command, **payload}
        try:
            self._ws.send(json.dumps(message))
            while True:
                reply = self._recv()
                if reply.get("id") == self._next_id:
                    break
        except (OSError, WebSocketException, TimeoutError) as exc:
            raise AssistBudgetError("err_connect", EXIT_CONNECTION, url=self._url, reason=str(exc) or type(exc).__name__) from exc
        if not reply.get("success", False):
            error = reply.get("error") or {}
            raise AssistBudgetError("err_ha_command", EXIT_CONNECTION, command=command,
                                    code=error.get("code", "?"), reason=error.get("message", ""))
        return reply.get("result")

    # -- the few commands assist-budget needs ------------------------------
    def get_version(self) -> str:
        """Home Assistant's version from ``get_config`` (falls back to the auth reply)."""
        config = self.call("get_config") or {}
        return str(config.get("version") or self.ha_version or "")

    def exposed_entities(self) -> dict[str, bool]:
        """Entities currently exposed to Assist (``homeassistant/expose_entity/list``)."""
        result = self.call("homeassistant/expose_entity/list") or {}
        listing = result.get("exposed_entities", {})
        return {eid: True for eid, assistants in listing.items() if assistants.get(ASSISTANT)}

    def set_exposed(self, entity_ids: list[str], should_expose: bool) -> list[str]:
        """Expose or hide entities; returns the ids HA says it changed."""
        result = self.call("homeassistant/expose_entity", assistants=[ASSISTANT],
                           entity_ids=entity_ids, should_expose=should_expose) or {}
        return list(result.get("changed_entity_ids", []))
