from __future__ import annotations


class FakeConnection:
    def __init__(self, *, fail_override: bool = False, close_raises: bool = False) -> None:
        self.commands: list[tuple[str | None, str, dict]] = []
        self.navigations: list[tuple[str, str]] = []
        self.targets = [FakeTarget("page-1", "page"), FakeTarget("worker-1", "service_worker")]
        self.events: list[str] = []
        self.fail_override = fail_override
        self.close_raises = close_raises
        self.closed = False

    def list_targets(self):
        return self.targets

    def attach_to_target(self, target_id: str):
        from app.runtime.cdp_client import CdpSession

        return CdpSession(session_id=f"session-{target_id}", connection=self)

    def send_command(self, method: str, params: dict | None = None, *, session_id: str | None = None):
        if self.fail_override and method == "Emulation.setTimezoneOverride":
            raise RuntimeError("timezone override failed")
        self.events.append(method)
        self.commands.append((session_id, method, params or {}))
        return {}

    def navigate(self, session_id: str, url: str) -> None:
        self.events.append("Page.navigate")
        self.navigations.append((session_id, url))

    def recv_message(self) -> dict:
        raise TimeoutError("no event")

    def set_timeout(self, timeout_s: float) -> None:
        return None

    def close(self) -> None:
        self.closed = True
        if self.close_raises:
            raise OSError("already closed")


class SlowNavigateConnection(FakeConnection):
    def navigate(self, session_id: str, url: str) -> None:
        super().navigate(session_id, url)
        raise TimeoutError("navigation response was slow")


class FakeTarget:
    def __init__(self, target_id: str, target_type: str) -> None:
        self.target_id = target_id
        self.type = target_type


def test_existing_page_targets_receive_timezone_language_and_return_start_session() -> None:
    from app.runtime.fingerprint_controller import apply_existing_page_targets

    cdp = FakeConnection()

    session_id = apply_existing_page_targets(
        cdp,
        _profile(),
    )

    assert ("session-page-1", "Emulation.setTimezoneOverride", {"timezoneId": "America/Los_Angeles"}) in cdp.commands
    ua = next(command for command in cdp.commands if command[1] == "Network.setUserAgentOverride")
    assert ua[0] == "session-page-1"
    assert ua[2]["acceptLanguage"] == "en-US,en;q=0.9"
    assert session_id == "session-page-1"
    assert cdp.navigations == []


def test_controller_enables_auto_attach_before_start_page_navigation() -> None:
    from app.runtime.fingerprint_controller import BrowserFingerprintController

    cdp = FakeConnection()
    controller = BrowserFingerprintController(
        connection_factory=lambda: cdp,
        profile=_profile(),
        start_url="https://www.browserscan.net/",
    )
    controller.start()
    controller.wait_ready(timeout_s=1)
    controller.stop()

    assert cdp.events.index("Target.setAutoAttach") < cdp.events.index("Page.navigate")
    assert cdp.navigations == [("session-page-1", "https://www.browserscan.net/")]


def test_controller_becomes_ready_when_start_navigation_response_is_slow() -> None:
    from app.runtime.fingerprint_controller import BrowserFingerprintController

    cdp = SlowNavigateConnection()
    controller = BrowserFingerprintController(
        connection_factory=lambda: cdp,
        profile=_profile(),
        start_url="https://www.browserscan.net/",
    )
    controller.start()
    controller.wait_ready(timeout_s=1)
    controller.stop()

    assert cdp.navigations == [("session-page-1", "https://www.browserscan.net/")]


def test_auto_attached_new_page_target_receives_fingerprint_before_resume() -> None:
    from app.runtime.fingerprint_controller import handle_auto_attached_target

    cdp = FakeConnection()
    handle_auto_attached_target(
        cdp,
        _profile(),
        {
            "method": "Target.attachedToTarget",
            "params": {
                "sessionId": "new-page-session",
                "targetInfo": {"targetId": "page-2", "type": "page"},
            },
        },
    )

    methods = [method for _, method, _ in cdp.commands]
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"
    assert ("new-page-session", "Emulation.setTimezoneOverride", {"timezoneId": "America/Los_Angeles"}) in cdp.commands


def test_auto_attached_target_is_resumed_even_when_fingerprint_override_fails() -> None:
    from app.runtime.fingerprint_controller import handle_auto_attached_target

    cdp = FakeConnection(fail_override=True)
    handled = handle_auto_attached_target(
        cdp,
        _profile(),
        {
            "method": "Target.attachedToTarget",
            "params": {
                "sessionId": "new-page-session",
                "targetInfo": {"targetId": "page-2", "type": "page"},
            },
        },
    )

    assert handled is True
    assert cdp.commands[-1] == ("new-page-session", "Runtime.runIfWaitingForDebugger", {})


def test_controller_stop_tolerates_already_closed_connection() -> None:
    from app.runtime.fingerprint_controller import BrowserFingerprintController

    cdp = FakeConnection(close_raises=True)
    controller = BrowserFingerprintController(
        connection_factory=lambda: cdp,
        profile=_profile(),
        start_url="https://www.browserscan.net/",
    )
    controller.start()
    controller.wait_ready(timeout_s=1)

    controller.stop()

    assert cdp.closed is True


def test_auto_attach_uses_wait_for_debugger_so_new_tabs_do_not_leak_local_timezone() -> None:
    from app.runtime.fingerprint_controller import enable_target_auto_attach

    cdp = FakeConnection()
    enable_target_auto_attach(cdp)

    assert cdp.commands == [
        (
            None,
            "Target.setAutoAttach",
            {
                "autoAttach": True,
                "waitForDebuggerOnStart": True,
                "flatten": True,
            },
        )
    ]


def _profile():
    from app.runtime.fingerprint import FingerprintProfile

    return FingerprintProfile(
        language="en-US",
        accept_language="en-US,en;q=0.9",
        timezone="America/Los_Angeles",
        os_family="windows",
        platform="Windows",
        navigator_platform="Win32",
        user_agent="Mozilla/5.0 Chrome/123.0.0.0",
        user_agent_metadata={"platform": "Windows"},
    )
