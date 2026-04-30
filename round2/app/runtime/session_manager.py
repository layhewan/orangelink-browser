from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.runtime.chromium_launcher import ChromiumLaunchResult, ChromiumLauncher
from app.runtime.config import LaunchConfig


@dataclass
class SessionState:
    session_id: str
    config: LaunchConfig
    status: str
    launch_result: ChromiumLaunchResult | None = None
    failure_reason: str | None = None


class SessionManager:
    def __init__(
        self,
        *,
        launcher: ChromiumLauncher,
        readiness_probe: Callable[[ChromiumLaunchResult], bool],
        max_sessions: int = 5,
    ) -> None:
        self.launcher = launcher
        self.readiness_probe = readiness_probe
        self.max_sessions = max_sessions
        self.sessions: dict[str, SessionState] = {}
        self._next_session_number = 1

    def launch(self, config: LaunchConfig, *, start_url: str) -> SessionState:
        session_id = self._allocate_session_id()
        session = SessionState(session_id=session_id, config=config, status="launching")
        self.sessions[session_id] = session

        try:
            launch_result = self.launcher.launch(
                config=config,
                session_id=session_id,
                start_url=start_url,
            )
            session.launch_result = launch_result
            if self.readiness_probe(launch_result):
                session.status = "running"
            else:
                session.status = "failed"
                session.failure_reason = "first page readiness failed"
        except Exception as exc:
            session.status = "failed"
            session.failure_reason = str(exc)

        return session

    def stop(self, session_id: str) -> None:
        session = self.sessions[session_id]
        session.status = "stopping"
        if session.launch_result is not None:
            self.launcher.stop(session.launch_result)
        session.status = "stopped"

    def stop_all(self) -> None:
        for session_id in list(self.sessions):
            if self.sessions[session_id].status not in {"stopped", "failed"}:
                self.stop(session_id)

    def _allocate_session_id(self) -> str:
        session_id = f"session-{self._next_session_number}"
        self._next_session_number += 1
        return session_id
