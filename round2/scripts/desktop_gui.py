import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.desktop.main import run_desktop_gui


if __name__ == "__main__":
    raise SystemExit(run_desktop_gui())
