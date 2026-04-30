from __future__ import annotations

from pathlib import Path


def test_proxy_session_adds_local_relay_proxy_server_arg() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(
            name="Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7890,
        ),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=34567,
        start_url="https://example.test/",
    )

    assert "--proxy-server=http://127.0.0.1:34567" in args
    assert "--proxy-bypass-list=<-loopback>" in args


def test_direct_session_does_not_add_proxy_server_arg() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(name="Direct"),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=None,
        start_url="https://example.test/",
    )

    assert not any(arg.startswith("--proxy-server=") for arg in args)
