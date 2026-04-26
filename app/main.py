from __future__ import annotations

from fastapi import FastAPI

from app.core.config import get_settings
from app.gui.server import build_gui_app
from app.services.detection_service import build_detection_app


def build_application() -> FastAPI:
    app = FastAPI(title="Privacy Browser Framework", version="1.0.0")
    gui_app = build_gui_app()
    detection_app = build_detection_app()

    app.mount("/detection", detection_app)
    app.mount("/", gui_app)
    return app


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:build_application",
        host=settings.gui_host,
        port=settings.gui_port,
        factory=True,
        reload=False,
    )


if __name__ == "__main__":
    run()
