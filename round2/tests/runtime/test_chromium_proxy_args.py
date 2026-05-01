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
    assert "--disable-breakpad" in args
    assert "--disable-crash-reporter" in args
    assert "--disable-async-dns" in args
    assert "--dns-prefetch-disable" in args
    assert "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1" in args


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
    assert "--disable-async-dns" not in args
    assert "--dns-prefetch-disable" not in args
    assert not any(arg.startswith("--host-resolver-rules=") for arg in args)


def test_extension_support_can_be_disabled() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(name="No Extensions", extension_support=False),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=None,
        start_url="https://example.test/",
    )

    assert "--disable-extensions" in args


def test_chromium_launch_sets_process_language_from_cached_proxy_language() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(
            name="US Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7897,
            cached_language="en-US",
        ),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=45678,
        start_url="https://example.test/",
    )

    assert "--lang=en-US" in args


def test_chromium_launch_sets_accept_language_from_cached_proxy_language() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(
            name="HK Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7897,
            cached_language="zh-HK",
        ),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=45678,
        start_url="https://example.test/",
    )

    assert "--accept-lang=zh-HK,zh;q=0.9" in args


def test_chromium_launch_uses_supported_ui_locale_without_changing_web_language() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(
            name="HK Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7897,
            cached_language="zh-HK",
        ),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=45678,
        start_url="https://example.test/",
    )

    assert "--lang=zh-TW" in args
    assert "--accept-lang=zh-HK,zh;q=0.9" in args


def test_chromium_launch_sanitizes_cached_accept_language_value() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(
            name="US Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7897,
            cached_language="en-US,en;q=0.9",
        ),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=45678,
        start_url="https://example.test/",
    )

    assert "--lang=en-US" in args
    assert "--accept-lang=en-US,en;q=0.9" in args
    assert not any(";q=" in arg for arg in args if arg.startswith("--lang="))


def test_direct_launch_ignores_stale_cached_proxy_language() -> None:
    from app.runtime.chromium_launcher import build_chromium_args
    from app.runtime.config import LaunchConfig

    args = build_chromium_args(
        config=LaunchConfig(
            name="Direct",
            proxy_enabled=False,
            manual_language="en-US",
            cached_language="zh-CN",
        ),
        chrome_executable=Path("runtime/chromium/chrome.exe"),
        profile_dir=Path("data/profiles/session-1"),
        remote_debugging_port=9222,
        relay_port=None,
        start_url="https://example.test/",
    )

    assert "--lang=en-US" in args
    assert "--lang=zh-CN" not in args
