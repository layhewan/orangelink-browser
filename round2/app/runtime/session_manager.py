from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.runtime.chromium_launcher import ChromiumLaunchResult, ChromiumLauncher
from app.runtime.config import LaunchConfig
from app.runtime.profiles import ProfileHandle, ProfileManager
from app.runtime.proxy_contract import ProxyMode


@dataclass
class SessionState:
    session_id: str
    config: LaunchConfig
    status: str
    launch_result: ChromiumLaunchResult | None = None
    failure_reason: str | None = None
    profile: ProfileHandle | None = None
    proxy_failure_count: int = 0


class SessionManager:
    def __init__(
        self,
        *,
        launcher: ChromiumLauncher,
        readiness_probe: Callable[[ChromiumLaunchResult], bool],
        max_sessions: int = 5,
        profile_manager: ProfileManager | None = None,
        diagnostics=None,
    ) -> None:
        self.launcher = launcher
        self.readiness_probe = readiness_probe
        self.max_sessions = max_sessions
        self.profile_manager = profile_manager
        self.diagnostics = diagnostics
        self.sessions: dict[str, SessionState] = {}
        self._next_session_number = 1

    def launch(
        self,
        config: LaunchConfig,
        *,
        start_url: str,
        saved_config_id: str | None = None,
    ) -> SessionState:
        session_id = self._allocate_session_id()
        rejection = self._launch_rejection_reason(config)
        if rejection is not None:
            session = SessionState(session_id=session_id, config=config, status="failed")
            self.sessions[session_id] = session
            session.status = "failed"
            session.failure_reason = rejection
            return session

        session = SessionState(session_id=session_id, config=config, status="launching")
        self.sessions[session_id] = session

        try:
            profile = self._profile_for_launch(session_id, saved_config_id)
            session.profile = profile
            launch_kwargs = {}
            if profile is not None:
                launch_kwargs["profile_dir"] = profile.path
            launch_result = self.launcher.launch(
                config=config,
                session_id=session_id,
                start_url=start_url,
                **launch_kwargs,
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

    def record_proxy_probe(self, session_id: str, *, ok: bool, detail: str) -> None:
        session = self.sessions[session_id]
        if not session.config.proxy_enabled:
            return

        if ok:
            session.proxy_failure_count = 0
            return

        session.proxy_failure_count += 1
        if session.proxy_failure_count >= 2:
            session.status = "network_failed_closed"
            if self.diagnostics is not None:
                self.diagnostics.log_event(
                    "proxy_loss_detected",
                    {"session_id": session.session_id, "detail": detail},
                )

    def stop(self, session_id: str) -> None:
        session = self.sessions[session_id]
        session.status = "stopping"
        if session.launch_result is not None:
            self.launcher.stop(session.launch_result)
        if self.profile_manager is not None and session.profile is not None:
            self.profile_manager.cleanup_temporary(session.profile)
        session.status = "stopped"

    def stop_all(self) -> None:
        for session_id in list(self.sessions):
            if self.sessions[session_id].status not in {"stopped", "failed"}:
                self.stop(session_id)

    def _allocate_session_id(self) -> str:
        session_id = f"session-{self._next_session_number}"
        self._next_session_number += 1
        return session_id

    def _launch_rejection_reason(self, config: LaunchConfig) -> str | None:
        if self._active_session_count() >= self.max_sessions:
            return f"最多只能同时运行 {self.max_sessions} 个会话"

        if config.proxy_enabled and not config.proxy_reuse_allowed:
            proxy_key = ProxyMode.from_config(config).reuse_key
            if proxy_key is not None and proxy_key in self._active_proxy_keys():
                return "同一代理已被运行中的会话使用"

        return None

    def _active_session_count(self) -> int:
        return sum(
            1
            for session in self.sessions.values()
            if session.status in {"launching", "running"}
        )

    def _active_proxy_keys(self) -> set[str]:
        keys: set[str] = set()
        for session in self.sessions.values():
            if session.status not in {"launching", "running"}:
                continue
            if not session.config.proxy_enabled:
                continue
            proxy_key = ProxyMode.from_config(session.config).reuse_key
            if proxy_key is not None:
                keys.add(proxy_key)
        return keys

    def _profile_for_launch(
        self,
        session_id: str,
        saved_config_id: str | None,
    ) -> ProfileHandle | None:
        if self.profile_manager is None:
            return None
        if saved_config_id is not None:
            return self.profile_manager.saved_config_profile(saved_config_id)
        return self.profile_manager.temporary_profile(session_id)
