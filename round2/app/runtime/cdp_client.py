from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.request import urlopen


@dataclass(frozen=True)
class CdpVersion:
    browser: str
    web_socket_debugger_url: str


@dataclass(frozen=True)
class CdpTarget:
    target_id: str
    type: str
    title: str = ""
    url: str = ""


@dataclass(frozen=True)
class CdpSession:
    session_id: str
    connection: "CdpConnection"


class CdpError(RuntimeError):
    pass


def wait_for_version(port: int, timeout_s: float) -> CdpVersion:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None

    while time.monotonic() <= deadline:
        try:
            with urlopen(
                f"http://127.0.0.1:{port}/json/version",
                timeout=min(0.5, max(timeout_s, 0.1)),
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return CdpVersion(
                browser=payload["Browser"],
                web_socket_debugger_url=payload["webSocketDebuggerUrl"],
            )
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)

    raise TimeoutError(f"CDP version endpoint did not become ready: {last_error}")


def connect_browser(websocket_url: str) -> "CdpConnection":
    from websockets.sync.client import connect

    return CdpConnection(connect(websocket_url))


class CdpConnection:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self._next_id = 0

    def list_targets(self) -> list[CdpTarget]:
        result = self._send("Target.getTargets")
        return [
            CdpTarget(
                target_id=target["targetId"],
                type=target.get("type", ""),
                title=target.get("title", ""),
                url=target.get("url", ""),
            )
            for target in result.get("targetInfos", [])
        ]

    def attach_to_target(self, target_id: str) -> CdpSession:
        result = self._send(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
        )
        return CdpSession(session_id=result["sessionId"], connection=self)

    def navigate(self, session_id: str, url: str) -> None:
        self._send("Page.navigate", {"url": url}, session_id=session_id)

    def evaluate(self, session_id: str, expression: str) -> object:
        result = self._send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            session_id=session_id,
        )
        return result.get("result", {}).get("value")

    def add_script_to_evaluate_on_new_document(self, session_id: str, source: str) -> None:
        self._send(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": source},
            session_id=session_id,
        )

    def close(self) -> None:
        self.websocket.close()

    def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self._send(method, params, session_id=session_id)

    def _send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._next_id += 1
        message: dict[str, Any] = {
            "id": self._next_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        if session_id is not None:
            message["sessionId"] = session_id

        self.websocket.send(json.dumps(message))

        while True:
            response = json.loads(self.websocket.recv())
            if response.get("id") != message["id"]:
                continue
            if "error" in response:
                raise CdpError(str(response["error"]))
            return response.get("result", {})
