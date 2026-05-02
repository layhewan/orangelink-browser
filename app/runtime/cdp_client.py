from __future__ import annotations

import json
import base64
import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
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
    return CdpConnection(_connect_websocket(websocket_url))


class CdpConnection:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self._next_id = 0
        self._pending_messages: list[dict[str, Any]] = []

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

    def recv_message(self) -> dict[str, Any]:
        if self._pending_messages:
            return self._pending_messages.pop(0)
        return self._read_next_message()

    def set_timeout(self, timeout_s: float) -> None:
        set_timeout = getattr(self.websocket, "set_timeout", None)
        if callable(set_timeout):
            set_timeout(timeout_s)

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
            response = self._read_next_message()
            if response.get("id") != message["id"]:
                self._pending_messages.append(response)
                continue
            if "error" in response:
                raise CdpError(str(response["error"]))
            return response.get("result", {})

    def _read_next_message(self) -> dict[str, Any]:
        return json.loads(self.websocket.recv())


class _StdlibWebSocket:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def send(self, payload: str) -> None:
        data = payload.encode("utf-8")
        header = bytearray([0x81])
        if len(data) < 126:
            header.append(0x80 | len(data))
        elif len(data) < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", len(data)))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", len(data)))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv(self) -> str:
        first = _recv_exact(self.sock, 2)
        if len(first) < 2:
            raise CdpError("CDP websocket closed")
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", _recv_exact(self.sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(self.sock, 8))[0]
        payload = _recv_exact(self.sock, length)
        if opcode == 0x08:
            raise CdpError("CDP websocket closed")
        if opcode != 0x01:
            return self.recv()
        return payload.decode("utf-8")

    def close(self) -> None:
        try:
            self.sock.sendall(bytes([0x88, 0x80]) + os.urandom(4))
        finally:
            self.sock.close()

    def set_timeout(self, timeout_s: float) -> None:
        self.sock.settimeout(timeout_s)


def _connect_websocket(websocket_url: str) -> _StdlibWebSocket:
    parsed = urlparse(websocket_url)
    if parsed.scheme != "ws":
        raise ValueError(f"only ws:// CDP URLs are supported: {websocket_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"

    sock = socket.create_connection((host, port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = _read_http_head(sock)
    if not response.startswith(b"HTTP/1.1 101") and not response.startswith(b"HTTP/1.0 101"):
        sock.close()
        raise CdpError(f"CDP websocket handshake failed: {response[:80]!r}")
    return _StdlibWebSocket(sock)


def _read_http_head(sock: socket.socket) -> bytes:
    data = bytearray()
    while not data.endswith(b"\r\n\r\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)
