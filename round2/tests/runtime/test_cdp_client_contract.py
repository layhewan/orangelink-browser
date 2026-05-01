from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def test_wait_for_version_reads_loopback_cdp_version_endpoint() -> None:
    from app.runtime.cdp_client import wait_for_version

    server = HTTPServer(("127.0.0.1", 0), VersionHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    try:
        version = wait_for_version(server.server_port, timeout_s=1)
    finally:
        server.server_close()
        thread.join(timeout=2)

    assert version.browser == "Chrome/123.0.0.0"
    assert version.web_socket_debugger_url == "ws://127.0.0.1/devtools/browser/test"


def test_cdp_connection_sends_expected_commands_with_session_id() -> None:
    from app.runtime.cdp_client import CdpConnection

    websocket = FakeWebSocket(
        [
            {"id": 1, "result": {"targetInfos": [{"targetId": "page-1", "type": "page"}]}},
            {"id": 2, "result": {}},
        ]
    )
    connection = CdpConnection(websocket)

    targets = connection.list_targets()
    connection.navigate("session-1", "https://example.test/")

    assert targets[0].target_id == "page-1"
    assert json.loads(websocket.sent[0])["method"] == "Target.getTargets"
    second = json.loads(websocket.sent[1])
    assert second["sessionId"] == "session-1"
    assert second["method"] == "Page.navigate"
    assert second["params"]["url"] == "https://example.test/"


def test_cdp_client_does_not_depend_on_external_websocket_package() -> None:
    source = Path("app/runtime/cdp_client.py").read_text(encoding="utf-8")

    assert "websockets" not in source


class VersionHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        assert self.path == "/json/version"
        body = json.dumps(
            {
                "Browser": "Chrome/123.0.0.0",
                "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/test",
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


class FakeWebSocket:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.sent: list[str] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def recv(self) -> str:
        return json.dumps(self.responses.pop(0))

    def close(self) -> None:
        self.closed = True
