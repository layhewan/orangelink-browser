from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.runtime.config import DEFAULT_START_PAGE, LaunchConfig, PortablePaths
from app.runtime.proxy_contract import ProxyMode


@dataclass(frozen=True)
class RelayProcess:
    process: Any
    port: int
    command: list[str]


@dataclass(frozen=True)
class ChromiumLaunchResult:
    process: Any
    args: list[str]
    cdp_port: int
    profile_dir: Path
    relay: RelayProcess | None


class ChromiumLauncher:
    def __init__(
        self,
        *,
        chrome_executable: Path,
        relay_executable: Path,
        paths: PortablePaths,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        port_allocator: Callable[[], int] | None = None,
    ) -> None:
        self.chrome_executable = chrome_executable
        self.relay_executable = relay_executable
        self.paths = paths
        self._popen = popen_factory
        self._port_allocator = port_allocator or _allocate_local_port

    def launch(
        self,
        *,
        config: LaunchConfig,
        session_id: str,
        start_url: str,
        profile_dir: Path | None = None,
    ) -> ChromiumLaunchResult:
        relay = self._start_relay(config) if config.proxy_enabled else None
        cdp_port = self._port_allocator()
        resolved_profile_dir = profile_dir or self.paths.profiles / session_id
        resolved_profile_dir.mkdir(parents=True, exist_ok=True)
        args = build_chromium_args(
            config=config,
            chrome_executable=self.chrome_executable,
            profile_dir=resolved_profile_dir,
            remote_debugging_port=cdp_port,
            relay_port=relay.port if relay else None,
            start_url=start_url,
        )
        process = self._popen(args)
        return ChromiumLaunchResult(
            process=process,
            args=args,
            cdp_port=cdp_port,
            profile_dir=resolved_profile_dir,
            relay=relay,
        )

    def stop(self, launch_result: ChromiumLaunchResult) -> None:
        _terminate_process(launch_result.process)
        if launch_result.relay is not None:
            _terminate_process(launch_result.relay.process)

    def _start_relay(self, config: LaunchConfig) -> RelayProcess:
        proxy_mode = ProxyMode.from_config(config)
        if proxy_mode.chromium_proxy_server is None:
            raise ValueError("proxy config is required to start relay")
        command = [
            str(self.relay_executable),
            "--mode",
            "proxy",
            "--upstream",
            proxy_mode.chromium_proxy_server,
            "--parent-pid",
            str(os.getpid()),
        ]
        process = self._popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ready_line = process.stdout.readline()
        if isinstance(ready_line, bytes):
            ready_line = ready_line.decode("utf-8", errors="replace")
        port = _parse_ready_port(str(ready_line))
        return RelayProcess(process=process, port=port, command=command)


def build_chromium_args(
    *,
    config: LaunchConfig,
    chrome_executable: Path,
    profile_dir: Path,
    remote_debugging_port: int,
    relay_port: int | None,
    start_url: str | None = None,
    homepage_file: Path | None = None,
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

    args.append(_resolve_start_url(start_url or config.start_page, homepage_file))
    return args


def _resolve_start_url(start_url: str, homepage_file: Path | None) -> str:
    if start_url == DEFAULT_START_PAGE and homepage_file is not None:
        return homepage_file.resolve().as_uri()
    return start_url


def _parse_ready_port(ready_line: str) -> int:
    for part in ready_line.split():
        if part.startswith("port="):
            return int(part.removeprefix("port="))
    raise RuntimeError(f"relay did not report ready port: {ready_line!r}")


def _terminate_process(process: Any) -> None:
    poll = getattr(process, "poll", None)
    if callable(poll) and poll() is not None:
        return
    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        terminate()


def _allocate_local_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
