from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import multiprocessing as mp
from multiprocessing.connection import Connection
import time
from typing import Any, Callable, Protocol

from app.worker.ipc import WorkerToMainType, parse_message
from app.worker.process_entry import worker_entry


class ProcessLike(Protocol):
    pid: int
    exitcode: int | None

    def start(self) -> None:
        ...

    def is_alive(self) -> bool:
        ...

    def terminate(self) -> None:
        ...

    def kill(self) -> None:
        ...

    def join(self, timeout: float | None = None) -> None:
        ...


@dataclass(slots=True)
class WorkerSpawnBundle:
    process: ProcessLike
    command_conn: Connection | None = None
    event_conn: Connection | None = None


Spawner = Callable[[str, dict[str, Any]], ProcessLike | WorkerSpawnBundle]


class ProfileRuntimeState(str, Enum):
    IDLE = "idle"
    LAUNCHING = "launching"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    CRASHED = "crashed"


_TERMINAL_STATES = {
    ProfileRuntimeState.STOPPED,
    ProfileRuntimeState.FAILED,
    ProfileRuntimeState.CRASHED,
}


@dataclass(slots=True)
class WorkerProcessRecord:
    profile_id: str
    process: ProcessLike
    pid: int
    launch_config: dict[str, Any] = field(default_factory=dict)
    state: ProfileRuntimeState = ProfileRuntimeState.IDLE
    created_at: float = 0.0
    updated_at: float = 0.0
    last_heartbeat_at: float | None = None
    exit_code: int | None = None
    exit_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    command_conn: Connection | None = None
    event_conn: Connection | None = None


class WorkerProcessManager:
    def __init__(
        self,
        *,
        spawner: Spawner | None = None,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self._spawner = spawner or _spawn_process
        self._time_fn = time_fn

        self._records: dict[str, WorkerProcessRecord] = {}
        self._profile_by_pid: dict[int, str] = {}

    def spawn(self, profile_id: str, launch_config: dict[str, Any]) -> WorkerProcessRecord:
        existing = self._records.get(profile_id)
        if existing is not None and existing.state not in _TERMINAL_STATES:
            raise ValueError(f"profile already has active worker: {profile_id}")

        spawn_result = self._spawner(profile_id, dict(launch_config))
        if isinstance(spawn_result, WorkerSpawnBundle):
            process = spawn_result.process
            command_conn = spawn_result.command_conn
            event_conn = spawn_result.event_conn
        else:
            process = spawn_result
            command_conn = None
            event_conn = None

        process.start()

        pid = getattr(process, "pid", None)
        if not isinstance(pid, int):
            raise RuntimeError("spawned worker process must expose integer pid")

        now = self._time_fn()
        record = WorkerProcessRecord(
            profile_id=profile_id,
            process=process,
            pid=pid,
            launch_config=dict(launch_config),
            state=ProfileRuntimeState.LAUNCHING,
            created_at=now,
            updated_at=now,
            command_conn=command_conn,
            event_conn=event_conn,
        )

        self._records[profile_id] = record
        self._profile_by_pid[pid] = profile_id
        return record

    def get_record(self, profile_id: str) -> WorkerProcessRecord | None:
        return self._records.get(profile_id)

    def get_state(self, profile_id: str) -> ProfileRuntimeState | None:
        record = self._records.get(profile_id)
        if record is None:
            return None
        return record.state

    def profile_for_pid(self, pid: int) -> str | None:
        return self._profile_by_pid.get(pid)

    def active_pids(self) -> list[int]:
        return sorted(self._profile_by_pid.keys())

    def active_profile_ids(self) -> list[str]:
        return sorted(
            profile_id
            for profile_id, record in self._records.items()
            if record.state not in _TERMINAL_STATES
        )

    def running_count(self) -> int:
        return sum(1 for rec in self._records.values() if rec.state == ProfileRuntimeState.RUNNING)

    def send_command(self, profile_id: str, message: dict[str, Any]) -> bool:
        record = self._records.get(profile_id)
        if record is None or record.command_conn is None:
            return False
        try:
            record.command_conn.send(message)
        except (BrokenPipeError, OSError):
            return False
        return True

    def poll_worker_events(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for profile_id, record in self._records.items():
            if record.event_conn is None:
                continue
            while True:
                try:
                    if not record.event_conn.poll():
                        break
                    raw = record.event_conn.recv()
                except (EOFError, OSError):
                    break
                if isinstance(raw, dict):
                    output.append(raw)
                    self.handle_worker_message(profile_id, raw)
        return output

    def mark_stopping(self, profile_id: str) -> bool:
        record = self._records.get(profile_id)
        if record is None:
            return False
        self._set_state(record, ProfileRuntimeState.STOPPING)
        return True

    def handle_worker_message(self, profile_id: str, raw_message: dict[str, Any]) -> bool:
        record = self._records.get(profile_id)
        if record is None:
            return False

        message = parse_message(raw_message)
        payload = dict(message.payload)

        pid_from_message = payload.get("pid")
        if isinstance(pid_from_message, int) and pid_from_message != record.pid:
            self._profile_by_pid.pop(record.pid, None)
            record.pid = pid_from_message
            self._profile_by_pid[record.pid] = profile_id

        message_type = message.type
        if message_type == WorkerToMainType.LAUNCH_STARTED.value:
            self._set_state(record, ProfileRuntimeState.LAUNCHING)
            return True

        if message_type == WorkerToMainType.LAUNCH_READY.value:
            self._set_state(record, ProfileRuntimeState.RUNNING)
            return True

        if message_type == WorkerToMainType.LAUNCH_FAILED.value:
            record.error_code = _optional_str(payload.get("error_code"))
            record.error_message = _optional_str(payload.get("error_message"))
            self._set_state(record, ProfileRuntimeState.FAILED)
            return True

        if message_type == WorkerToMainType.HEALTH_REPORT.value:
            heartbeat_at = payload.get("heartbeat_at")
            if heartbeat_at is None:
                heartbeat_at = self._time_fn()
            record.last_heartbeat_at = float(heartbeat_at)
            record.updated_at = self._time_fn()
            return True

        if message_type == WorkerToMainType.WORKER_EXITED.value:
            record.exit_code = _optional_int(payload.get("exit_code"), default=record.exit_code)
            record.exit_reason = _optional_str(payload.get("exit_reason"))
            next_state = self._state_for_exit(record.exit_reason, record.exit_code)
            self._set_state(record, next_state)
            self._profile_by_pid.pop(record.pid, None)
            return True

        if message_type == WorkerToMainType.SNAPSHOT_COLLECTED.value:
            record.updated_at = self._time_fn()
            return True

        return False

    def monitor(self) -> list[WorkerProcessRecord]:
        transitioned: list[WorkerProcessRecord] = []
        for record in self._records.values():
            if record.state in _TERMINAL_STATES:
                continue

            if record.process.is_alive():
                continue

            exit_code = getattr(record.process, "exitcode", None)
            record.exit_code = exit_code

            if record.state == ProfileRuntimeState.STOPPING:
                record.exit_reason = "normal"
                next_state = ProfileRuntimeState.STOPPED
            elif record.state == ProfileRuntimeState.LAUNCHING:
                record.exit_reason = "crash"
                next_state = ProfileRuntimeState.FAILED
            elif exit_code in (None, 0):
                record.exit_reason = "normal"
                next_state = ProfileRuntimeState.STOPPED
            else:
                record.exit_reason = "crash"
                next_state = ProfileRuntimeState.CRASHED

            self._set_state(record, next_state)
            self._profile_by_pid.pop(record.pid, None)
            transitioned.append(record)

        return transitioned

    def reap(self, profile_id: str, *, force: bool = False, timeout_s: float = 5.0) -> bool:
        record = self._records.get(profile_id)
        if record is None:
            return False

        process = record.process
        if process.is_alive():
            if force:
                process.kill()
            else:
                process.terminate()

            process.join(timeout=timeout_s)
            if not force and process.is_alive():
                process.kill()
                process.join(timeout=timeout_s)

        record.exit_code = getattr(process, "exitcode", record.exit_code)
        if force:
            record.exit_reason = "killed"
        elif record.exit_reason is None:
            record.exit_reason = "normal"

        self._set_state(record, ProfileRuntimeState.STOPPED)
        self._profile_by_pid.pop(record.pid, None)
        if record.command_conn is not None:
            record.command_conn.close()
        if record.event_conn is not None:
            record.event_conn.close()
        return True

    def _set_state(self, record: WorkerProcessRecord, state: ProfileRuntimeState) -> None:
        record.state = state
        record.updated_at = self._time_fn()

    @staticmethod
    def _state_for_exit(
        exit_reason: str | None,
        exit_code: int | None,
    ) -> ProfileRuntimeState:
        normalized_reason = (exit_reason or "").strip().lower()
        if normalized_reason in {"crash", "crashed"}:
            return ProfileRuntimeState.CRASHED
        if normalized_reason in {"normal", "stopped", "killed", "timeout"}:
            return ProfileRuntimeState.STOPPED
        if exit_code not in (None, 0):
            return ProfileRuntimeState.CRASHED
        return ProfileRuntimeState.STOPPED


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _optional_int(value: Any, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    return int(value)


def _spawn_process(profile_id: str, launch_config: dict[str, Any]) -> WorkerSpawnBundle:
    worker_cmd, main_cmd = mp.Pipe(duplex=False)
    main_evt, worker_evt = mp.Pipe(duplex=False)
    process = mp.Process(
        target=worker_entry,
        args=(profile_id, launch_config, worker_cmd, worker_evt),
        daemon=True,
    )
    return WorkerSpawnBundle(process=process, command_conn=main_cmd, event_conn=main_evt)
