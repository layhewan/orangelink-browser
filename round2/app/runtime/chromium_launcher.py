from __future__ import annotations

import os
import queue
import subprocess
import threading
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
        relay_ready_timeout_s: float = 5,
    ) -> None:
        self.chrome_executable = chrome_executable
        self.relay_executable = relay_executable
        self.paths = paths
        self._popen = popen_factory
        self._port_allocator = port_allocator or _allocate_local_port
        self._relay_ready_timeout_s = relay_ready_timeout_s

    def launch(
        self,
        *,
        config: LaunchConfig,
        session_id: str,
        start_url: str,
        profile_dir: Path | None = None,
    ) -> ChromiumLaunchResult:
        relay = self._start_relay(config, session_id=session_id) if config.proxy_enabled else None
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
        chromium_log = self.paths.logs / f"chromium-{session_id}.log"
        chromium_log.parent.mkdir(parents=True, exist_ok=True)
        chromium_output = chromium_log.open("ab")
        try:
            process = self._popen(
                args,
                stdout=chromium_output,
                stderr=chromium_output,
                **_hidden_child_process_kwargs(),
            )
        except Exception:
            if relay is not None:
                _terminate_process(relay.process)
            raise
        finally:
            chromium_output.close()
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

    def _start_relay(self, config: LaunchConfig, *, session_id: str) -> RelayProcess:
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
        relay_log = self.paths.logs / f"proxy-relay-{session_id}.log"
        relay_log.parent.mkdir(parents=True, exist_ok=True)
        stderr_log = relay_log.open("ab")
        try:
            process = self._popen(
                command,
                stdout=subprocess.PIPE,
                stderr=stderr_log,
                **_hidden_child_process_kwargs(),
            )
        finally:
            stderr_log.close()
        ready_line = _read_ready_line(process, timeout_s=self._relay_ready_timeout_s)
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
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--disable-session-crashed-bubble",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=DnsOverHttps,UseDnsHttpsSvcb,Quic",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        f"--lang={_launch_language(config)}",
        "--proxy-bypass-list=<-loopback>",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={remote_debugging_port}",
        f"--user-data-dir={profile_dir}",
    ]

    if not config.extension_support:
        args.append("--disable-extensions")

    if config.proxy_enabled:
        args.append(f"--proxy-server=http://127.0.0.1:{relay_port}")
        args.append("--disable-async-dns")
        args.append("--dns-prefetch-disable")
        args.append("--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1")

    args.append(_resolve_start_url(start_url or config.start_page, homepage_file))
    return args


def _resolve_start_url(start_url: str, homepage_file: Path | None) -> str:
    if start_url == DEFAULT_START_PAGE and homepage_file is not None:
        return homepage_file.resolve().as_uri()
    return start_url


def _launch_language(config: LaunchConfig) -> str:
    if config.automatic_language:
        return (config.cached_language if config.proxy_enabled else "") or config.manual_language
    return config.manual_language


def _parse_ready_port(ready_line: str) -> int:
    for part in ready_line.split():
        if part.startswith("port="):
            return int(part.removeprefix("port="))
    raise RuntimeError(f"relay did not report ready port: {ready_line!r}")


def _read_ready_line(process: Any, *, timeout_s: float) -> str | bytes:
    output: queue.Queue[str | bytes | BaseException] = queue.Queue(maxsize=1)

    def read_line() -> None:
        try:
            output.put(process.stdout.readline())
        except BaseException as exc:
            output.put(exc)

    thread = threading.Thread(target=read_line, daemon=True)
    thread.start()
    try:
        result = output.get(timeout=timeout_s)
    except queue.Empty as exc:
        _terminate_process(process)
        raise RuntimeError(f"relay did not report ready within {timeout_s:g}s") from exc
    if isinstance(result, BaseException):
        raise result
    return result


def _terminate_process(process: Any) -> None:
    poll = getattr(process, "poll", None)
    if callable(poll) and poll() is not None:
        return
    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        terminate()
        if _wait_for_process_exit(process, timeout_s=5):
            return

    kill = getattr(process, "kill", None)
    if callable(kill):
        kill()
        _wait_for_process_exit(process, timeout_s=2)


def _wait_for_process_exit(process: Any, *, timeout_s: float) -> bool:
    wait = getattr(process, "wait", None)
    if not callable(wait):
        return True
    try:
        wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False
    except TypeError:
        wait()
    return True


def _allocate_local_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _hidden_child_process_kwargs() -> dict[str, int]:
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": create_no_window} if create_no_window else {}
