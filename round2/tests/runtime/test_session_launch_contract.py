from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path


class FakeStdout:
    def __init__(self, line: str) -> None:
        self._line = line.encode("utf-8")

    def readline(self) -> bytes:
        return self._line


class FakeProcess:
    _next_pid = 1000

    def __init__(self, stdout_line: str | None = None) -> None:
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self.stdout = FakeStdout(stdout_line or "")
        self.terminated = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True


class WaitableProcess:
    _next_pid = 2000

    def __init__(self, *, exits_on_wait: bool = True) -> None:
        WaitableProcess._next_pid += 1
        self.pid = WaitableProcess._next_pid
        self.stdout = FakeStdout("")
        self.exits_on_wait = exits_on_wait
        self.exited = False
        self.terminated = False
        self.killed = False
        self.wait_timeouts: list[float] = []

    def poll(self) -> int | None:
        return 0 if self.exited else None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.exited = True

    def wait(self, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        if self.exited or self.exits_on_wait:
            self.exited = True
            return 0
        raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)


class RecordingPopen:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, args: list[str], **kwargs) -> FakeProcess:
        self.calls.append([str(arg) for arg in args])
        self.kwargs.append(kwargs)
        if "proxy-relay.exe" in str(args[0]):
            return FakeProcess("RELAY_READY port=45678 mode=proxy\n")
        return FakeProcess()


class HangingStdout:
    def readline(self) -> bytes:
        time.sleep(2)
        return b""


class HangingRelayProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stdout = HangingStdout()


class FailingChromePopen(RecordingPopen):
    def __call__(self, args: list[str], **kwargs) -> FakeProcess:
        self.calls.append([str(arg) for arg in args])
        self.kwargs.append(kwargs)
        if "proxy-relay.exe" in str(args[0]):
            self.relay = FakeProcess("RELAY_READY port=45678 mode=proxy\n")
            return self.relay
        raise OSError("chrome launch failed")


def test_proxy_session_starts_relay_before_chromium_and_uses_local_proxy() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()
    recorder = RecordingPopen()
    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=recorder,
        port_allocator=lambda: 9222,
    )

    result = launcher.launch(
        config=LaunchConfig(
            name="Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7890,
        ),
        session_id="session-1",
        start_url="https://example.test/",
    )

    assert "proxy-relay.exe" in recorder.calls[0][0]
    assert "chrome.exe" in recorder.calls[1][0]
    assert "--proxy-server=http://127.0.0.1:45678" in result.args
    assert "--remote-debugging-address=127.0.0.1" in result.args
    assert "--remote-debugging-port=9222" in result.args
    assert result.relay is not None
    assert result.profile_dir == base / "data" / "profiles" / "session-1"


def test_proxy_relay_stderr_is_logged_instead_of_left_as_unread_pipe() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()
    recorder = RecordingPopen()
    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=recorder,
        port_allocator=lambda: 9222,
    )

    launcher.launch(
        config=LaunchConfig(
            name="Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7890,
        ),
        session_id="session-1",
        start_url="https://example.test/",
    )

    assert recorder.kwargs[0]["stdout"] == subprocess.PIPE
    assert recorder.kwargs[0]["stderr"] != subprocess.PIPE
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        assert recorder.kwargs[0]["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert base.joinpath("data", "logs", "proxy-relay-session-1.log").exists()


def test_chromium_stderr_is_logged_for_packaged_launch_diagnostics() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()
    recorder = RecordingPopen()
    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=recorder,
        port_allocator=lambda: 9222,
    )

    launcher.launch(
        config=LaunchConfig(name="Direct"),
        session_id="session-logs",
        start_url="https://example.test/",
    )

    assert recorder.kwargs[0]["stdout"] != subprocess.PIPE
    assert recorder.kwargs[0]["stderr"] != subprocess.PIPE
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        assert recorder.kwargs[0]["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert base.joinpath("data", "logs", "chromium-session-logs.log").exists()


def test_chromium_launcher_persists_profile_accept_language_preference() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()
    recorder = RecordingPopen()
    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=recorder,
        port_allocator=lambda: 9222,
    )

    result = launcher.launch(
        config=LaunchConfig(
            name="HK",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7897,
            cached_language="zh-HK",
        ),
        session_id="session-language",
        start_url="https://example.test/",
    )

    preferences = json.loads((result.profile_dir / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert preferences["intl"]["accept_languages"] == "zh-HK,zh;q=0.9"


def test_chromium_launcher_keeps_hong_kong_web_locale_when_ui_locale_falls_back() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()
    recorder = RecordingPopen()
    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=recorder,
        port_allocator=lambda: 9222,
    )

    result = launcher.launch(
        config=LaunchConfig(
            name="HK",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7897,
            cached_language="zh-HK",
        ),
        session_id="session-hk",
        start_url="https://example.test/",
    )

    assert "--lang=zh-TW" in result.args
    assert "--accept-lang=zh-HK,zh;q=0.9" in result.args


def test_proxy_relay_ready_wait_times_out_instead_of_hanging_gui() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()

    def popen(args: list[str], **kwargs) -> FakeProcess:
        return HangingRelayProcess()

    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=popen,
        relay_ready_timeout_s=0.05,
    )

    try:
        launcher.launch(
            config=LaunchConfig(
                name="Proxy",
                proxy_enabled=True,
                proxy_host="127.0.0.1",
                proxy_port=7890,
            ),
            session_id="session-timeout",
            start_url="https://example.test/",
        )
    except RuntimeError as exc:
        assert "relay did not report ready within" in str(exc)
    else:
        raise AssertionError("relay ready wait should time out")


def test_relay_is_stopped_when_chromium_launch_fails() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()
    recorder = FailingChromePopen()
    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=recorder,
        port_allocator=lambda: 9222,
    )

    try:
        launcher.launch(
            config=LaunchConfig(
                name="Proxy",
                proxy_enabled=True,
                proxy_host="127.0.0.1",
                proxy_port=7890,
            ),
            session_id="session-fails",
            start_url="https://example.test/",
        )
    except OSError:
        pass
    else:
        raise AssertionError("chrome launch should fail")

    assert recorder.relay.terminated is True


def test_chromium_launcher_stop_waits_for_child_processes_to_exit() -> None:
    from app.runtime.chromium_launcher import ChromiumLaunchResult, ChromiumLauncher, RelayProcess
    from app.runtime.config import resolve_portable_paths

    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=_reset_runtime_base(), create=True),
    )
    browser = WaitableProcess()
    relay = WaitableProcess()

    launcher.stop(
        ChromiumLaunchResult(
            process=browser,
            args=[],
            cdp_port=9222,
            profile_dir=Path("data/profiles/session-1"),
            relay=RelayProcess(process=relay, port=45678, command=[]),
        )
    )

    assert browser.terminated is True
    assert relay.terminated is True
    assert browser.wait_timeouts == [5]
    assert relay.wait_timeouts == [5]
    assert browser.killed is False
    assert relay.killed is False


def test_chromium_launcher_stop_kills_child_when_terminate_does_not_exit() -> None:
    from app.runtime.chromium_launcher import ChromiumLaunchResult, ChromiumLauncher
    from app.runtime.config import resolve_portable_paths

    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=_reset_runtime_base(), create=True),
    )
    browser = WaitableProcess(exits_on_wait=False)

    launcher.stop(
        ChromiumLaunchResult(
            process=browser,
            args=[],
            cdp_port=9222,
            profile_dir=Path("data/profiles/session-1"),
            relay=None,
        )
    )

    assert browser.terminated is True
    assert browser.killed is True
    assert browser.wait_timeouts == [5, 2]


def test_direct_session_has_no_proxy_relay_or_proxy_credentials() -> None:
    from app.runtime.chromium_launcher import ChromiumLauncher
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    base = _reset_runtime_base()
    recorder = RecordingPopen()
    launcher = ChromiumLauncher(
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        relay_executable=Path("proxy-relay.exe"),
        paths=resolve_portable_paths(base=base, create=True),
        popen_factory=recorder,
        port_allocator=lambda: 9333,
    )

    result = launcher.launch(
        config=LaunchConfig(name="Direct"),
        session_id="session-2",
        start_url="https://example.test/",
    )

    assert len(recorder.calls) == 1
    assert result.relay is None
    assert not any(arg.startswith("--proxy-server=") for arg in result.args)
    assert "secret" not in json.dumps(result.args)


def test_chromium_launcher_source_uses_subprocess_without_browser_frameworks() -> None:
    source = Path("app/runtime/chromium_launcher.py").read_text(encoding="utf-8")

    assert "subprocess.Popen" in source
    for forbidden in ("selenium", "playwright", "chromedriver"):
        assert forbidden not in source.lower()


def test_pyproject_declares_native_cdp_dependency_only() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8").lower()

    assert "websockets" not in pyproject
    assert "selenium" not in pyproject
    assert "playwright" not in pyproject


def _reset_runtime_base() -> Path:
    base = Path(__file__).resolve().parent / "_tmp_runtime_base"
    shutil.rmtree(base, ignore_errors=True)
    return base
