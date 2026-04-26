from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.runtime import AppRuntime


class LaunchBatchRequest(BaseModel):
    profile_ids: list[int] = Field(default_factory=list)
    template_id: int | None = None


class CreateProfileRequest(BaseModel):
    name: str
    allow_proxy_reuse: bool = False
    profile_template_overrides_json: dict = Field(default_factory=dict)


class CreateTemplateRequest(BaseModel):
    name: str
    description: str | None = None
    config_json: dict = Field(default_factory=dict)
    enabled: bool = True


def build_gui_app(runtime: AppRuntime | None = None) -> FastAPI:
    runtime = runtime or AppRuntime()
    runtime.start()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="Privacy Browser Framework GUI", version="1.0.0", lifespan=lifespan)
    app.state.runtime = runtime

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/profiles")
    def list_profiles() -> list[dict]:
        return runtime.repository.list_profiles()

    @app.post("/api/profiles")
    def create_profile(req: CreateProfileRequest) -> dict:
        profile_id = runtime.repository.create_profile(
            name=req.name,
            allow_proxy_reuse=req.allow_proxy_reuse,
            profile_template_overrides_json=req.profile_template_overrides_json,
        )
        return {"id": profile_id}

    @app.get("/api/templates")
    def list_templates() -> list[dict]:
        return runtime.repository.list_profile_templates()

    @app.post("/api/templates")
    def create_template(req: CreateTemplateRequest) -> dict:
        template_id = runtime.repository.create_profile_template(
            name=req.name,
            description=req.description,
            config_json=req.config_json,
            enabled=req.enabled,
        )
        return {"id": template_id}

    @app.post("/api/batches/launch")
    def launch_batch(req: LaunchBatchRequest) -> dict:
        if not req.profile_ids:
            raise HTTPException(status_code=400, detail="profile_ids is required")
        return runtime.launch_batch(req.profile_ids, req.template_id)

    @app.get("/api/batches")
    def list_batches() -> list[dict]:
        return runtime.repository.list_launch_batches()

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: int) -> dict:
        result = runtime.get_batch(batch_id)
        if result is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return result

    @app.post("/api/profiles/{profile_id}/snapshot")
    def collect_snapshot(profile_id: str) -> dict:
        return {"ok": runtime.collect_snapshot(profile_id)}

    @app.post("/api/profiles/{profile_id}/stop")
    def stop_profile(profile_id: str) -> dict:
        return {"ok": runtime.stop_profile(profile_id)}

    @app.post("/api/profiles/{profile_id}/destroy")
    def destroy_profile(profile_id: str) -> dict:
        return {"ok": runtime.destroy_profile_env(profile_id)}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app
