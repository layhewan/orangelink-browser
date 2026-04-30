from __future__ import annotations

from pathlib import Path

from app.runtime.config import LaunchConfig


def build_chromium_args(
    *,
    config: LaunchConfig,
    chrome_executable: Path,
    profile_dir: Path,
    remote_debugging_port: int,
    relay_port: int | None,
    start_url: str | None = None,
) -> list[str]:
    if config.proxy_enabled and relay_port is None:
        raise ValueError("proxy relay port is required for proxy-enabled sessions")

    args = [
        str(chrome_executable),
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=DnsOverHttps,UseDnsHttpsSvcb,Quic",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--proxy-bypass-list=<-loopback>",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={remote_debugging_port}",
        f"--user-data-dir={profile_dir}",
    ]

    if config.proxy_enabled:
        args.append(f"--proxy-server=http://127.0.0.1:{relay_port}")

    args.append(start_url or config.start_page)
    return args
