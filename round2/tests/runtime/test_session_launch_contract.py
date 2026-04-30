from __future__ import annotations

import json
import shutil
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


class RecordingPopen:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs) -> FakeProcess:
        self.calls.append([str(arg) for arg in args])
        if "proxy-relay.exe" in str(args[0]):
            return FakeProcess("RELAY_READY port=45678 mode=proxy\n")
        return FakeProcess()


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

    assert "websockets>=16.0" in pyproject
    assert "selenium" not in pyproject
    assert "playwright" not in pyproject


def _reset_runtime_base() -> Path:
    base = Path(__file__).resolve().parent / "_tmp_runtime_base"
    shutil.rmtree(base, ignore_errors=True)
    return base
