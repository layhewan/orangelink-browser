from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel


class ProbePayload(BaseModel):
    profile_id: int
    worker_pid: int | None = None
    ip_timezone: str | None = None
    local_timezone: str | None = None
    bot_detected: bool = False
    ip_mismatch: bool = False
    webrtc_leak: bool = False


@dataclass(slots=True)
class Penalty:
    code: str
    score_delta: int
    reason: str


def calculate_score(payload: ProbePayload) -> dict:
    penalties: list[Penalty] = []

    if payload.ip_timezone and payload.local_timezone and payload.ip_timezone != payload.local_timezone:
        penalties.append(
            Penalty(
                code="timezone_mismatch",
                score_delta=-10,
                reason="IP timezone and local timezone mismatch",
            )
        )
    if payload.bot_detected:
        penalties.append(Penalty(code="bot_detected", score_delta=-5, reason="Automation characteristics detected"))
    if payload.ip_mismatch:
        penalties.append(Penalty(code="ip_mismatch", score_delta=-10, reason="Public IP mismatch"))
    if payload.webrtc_leak:
        penalties.append(Penalty(code="webrtc_leak", score_delta=-10, reason="WebRTC local IP leak"))

    score = max(0, 100 + sum(p.score_delta for p in penalties))
    return {
        "snapshot_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "score": score,
        "penalties": [asdict(p) for p in penalties],
    }


def build_detection_app() -> FastAPI:
    app = FastAPI(title="Local Detection Service", version="1.0.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/probe")
    def probe(payload: ProbePayload) -> dict:
        return calculate_score(payload)

    return app
