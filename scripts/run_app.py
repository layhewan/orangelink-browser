from __future__ import annotations

from multiprocessing import freeze_support
from pathlib import Path
import subprocess
import threading
import time
from urllib.request import urlopen
import os
import sys

import uvicorn

from app.core.config import get_settings


def _prepare_runtime_cwd() -> None:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        os.chdir(exe_dir)


def _wait_for_server_ready(url: str, timeout_s: float = 25.0) -> bool:
    deadline = time.time() + timeout_s
    health_url = f"{url.rstrip('/')}/api/health"
    while time.time() < deadline:
        try:
            with urlopen(health_url, timeout=2) as response:  # noqa: S310
                if response.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


def _resolve_chrome_path(raw_path: Path) -> Path:
    if raw_path.is_absolute():
        return raw_path
    return (Path.cwd() / raw_path).resolve()


def _launch_embedded_gui_window(url: str, chrome_path: Path) -> subprocess.Popen | None:
    if not chrome_path.exists():
        return None
    user_data_dir = (Path.cwd() / "data" / "gui-shell").resolve()
    user_data_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(chrome_path),
        f"--app={url}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
    ]
    return subprocess.Popen(cmd)


def run_desktop_gui() -> int:
    settings = get_settings()
    app_url = f"http://{settings.gui_host}:{settings.gui_port}/"
    config = uvicorn.Config(
        "app.main:build_application",
        host=settings.gui_host,
        port=settings.gui_port,
        factory=True,
        reload=False,
        log_level=str(settings.log_level).lower(),
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not _wait_for_server_ready(app_url):
        server.should_exit = True
        server_thread.join(timeout=6.0)
        return 2

    chrome_path = _resolve_chrome_path(settings.chrome_executable_path)
    gui_process = _launch_embedded_gui_window(app_url, chrome_path)
    if gui_process is None:
        server.should_exit = True
        server_thread.join(timeout=6.0)
        return 3

    exit_code = 0
    try:
        gui_process.wait()
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        server.should_exit = True
        server_thread.join(timeout=8.0)
    return exit_code


if __name__ == "__main__":
    freeze_support()
    _prepare_runtime_cwd()
    raise SystemExit(run_desktop_gui())
