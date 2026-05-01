import sys
from pathlib import Path
import json

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_LOG_STREAM = None


def _install_windowed_log_streams() -> None:
    global _LOG_STREAM
    if sys.stdout is not None and sys.stderr is not None:
        return

    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else REPO_ROOT
    log_dir = base / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_STREAM = (log_dir / "desktop-gui.log").open("a", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _LOG_STREAM
    if sys.stderr is None:
        sys.stderr = _LOG_STREAM


_install_windowed_log_streams()


def _write_startup_trace() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = Path(sys.executable).resolve().parent
    log_dir = base / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "desktop-startup.json").write_text(
        json.dumps(
            {
                "argv": sys.argv,
                "cwd": str(Path.cwd()),
                "executable": sys.executable,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


_write_startup_trace()

from app.desktop.main import run_desktop_gui


if __name__ == "__main__":
    raise SystemExit(
        run_desktop_gui(
            smoke="--smoke" in sys.argv,
            launch_smoke="--launch-smoke" in sys.argv,
            launch_smoke_proxy="--launch-smoke-proxy" in sys.argv,
        )
    )
