from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Mapping

from app.worker.ipc import WorkerToMainType, build_worker_message


MessageSender = Callable[[dict[str, Any]], None]
StateProvider = Callable[[], str | None]


@dataclass(slots=True)
class HealthStatus:
    last_heartbeat_at: float | None = None
    exit_reason: str | None = None
    exit_code: int | None = None


class WorkerHealthReporter:
    def __init__(
        self,
        *,
        worker_id: str,
        sender: MessageSender,
        heartbeat_interval_s: float = 5.0,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if heartbeat_interval_s <= 0:
            raise ValueError("heartbeat_interval_s must be > 0")

        self.worker_id = worker_id
        self._sender = sender
        self._heartbeat_interval_s = heartbeat_interval_s
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn

        self._status = HealthStatus()
        self._state_provider: StateProvider | None = None
        self._pid: int | None = None

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def status(self) -> HealthStatus:
        return self._status

    def emit_heartbeat(
        self,
        *,
        pid: int | None = None,
        state: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._time_fn()
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "heartbeat_at": now,
        }
        if state is not None:
            payload["state"] = state
        if extra:
            payload.update(dict(extra))

        message = build_worker_message(
            WorkerToMainType.HEALTH_REPORT,
            payload=payload,
            worker_pid=pid,
        )
        self._sender(message)

        self._status.last_heartbeat_at = now
        return message

    def emit_exit(
        self,
        *,
        exit_reason: str,
        pid: int | None = None,
        exit_code: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "exit_reason": exit_reason,
        }
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)
        if extra:
            payload.update(dict(extra))

        message = build_worker_message(
            WorkerToMainType.WORKER_EXITED,
            payload=payload,
            worker_pid=pid,
        )
        self._sender(message)

        self._status.exit_reason = exit_reason
        self._status.exit_code = exit_code
        return message

    def start(
        self,
        *,
        pid: int | None = None,
        state_provider: StateProvider | None = None,
    ) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._pid = pid
        self._state_provider = state_provider
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            state = self._state_provider() if self._state_provider else None
            self.emit_heartbeat(pid=self._pid, state=state)
            self._sleep_fn(self._heartbeat_interval_s)

    def stop(
        self,
        *,
        exit_reason: str = "normal",
        pid: int | None = None,
        exit_code: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=self._heartbeat_interval_s + 0.5)
        self._thread = None

        final_pid = self._pid if pid is None else pid
        self.emit_exit(
            exit_reason=exit_reason,
            pid=final_pid,
            exit_code=exit_code,
            extra=extra,
        )
