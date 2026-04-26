from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Mapping


class MainToWorkerType(str, Enum):
    LAUNCH_PROFILE = "launch_profile"
    COLLECT_SNAPSHOT = "collect_snapshot"
    STOP_PROFILE = "stop_profile"
    DESTROY_PROFILE_ENV = "destroy_profile_env"
    PING = "ping"


class WorkerToMainType(str, Enum):
    LAUNCH_STARTED = "launch_started"
    LAUNCH_READY = "launch_ready"
    LAUNCH_FAILED = "launch_failed"
    SNAPSHOT_COLLECTED = "snapshot_collected"
    HEALTH_REPORT = "health_report"
    WORKER_EXITED = "worker_exited"


_ALL_MAIN_TYPES = {message_type.value for message_type in MainToWorkerType}
_ALL_WORKER_TYPES = {message_type.value for message_type in WorkerToMainType}
_ALL_MESSAGE_TYPES = _ALL_MAIN_TYPES | _ALL_WORKER_TYPES


@dataclass(frozen=True, slots=True)
class IPCMessage:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    profile_id: str | None = None
    worker_pid: int | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }
        if self.profile_id is not None:
            data["profile_id"] = self.profile_id
        if self.worker_pid is not None:
            data["worker_pid"] = self.worker_pid
        return data


def is_main_to_worker_type(message_type: str) -> bool:
    return message_type in _ALL_MAIN_TYPES


def is_worker_to_main_type(message_type: str) -> bool:
    return message_type in _ALL_WORKER_TYPES


def _normalize_message_type(message_type: MainToWorkerType | WorkerToMainType | str) -> str:
    if isinstance(message_type, Enum):
        normalized = str(message_type.value)
    else:
        normalized = str(message_type)
    if normalized not in _ALL_MESSAGE_TYPES:
        raise ValueError(f"unknown ipc message type: {normalized}")
    return normalized


def build_message(
    message_type: MainToWorkerType | WorkerToMainType | str,
    *,
    payload: Mapping[str, Any] | None = None,
    profile_id: str | None = None,
    worker_pid: int | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    normalized_type = _normalize_message_type(message_type)
    message = IPCMessage(
        type=normalized_type,
        payload=dict(payload or {}),
        profile_id=profile_id,
        worker_pid=worker_pid,
        timestamp=time.time() if timestamp is None else float(timestamp),
    )
    return message.to_dict()


def build_main_message(
    message_type: MainToWorkerType | str,
    *,
    payload: Mapping[str, Any] | None = None,
    profile_id: str | None = None,
    worker_pid: int | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    normalized_type = _normalize_message_type(message_type)
    if not is_main_to_worker_type(normalized_type):
        raise ValueError(f"message type is not main->worker: {normalized_type}")
    return build_message(
        normalized_type,
        payload=payload,
        profile_id=profile_id,
        worker_pid=worker_pid,
        timestamp=timestamp,
    )


def build_worker_message(
    message_type: WorkerToMainType | str,
    *,
    payload: Mapping[str, Any] | None = None,
    profile_id: str | None = None,
    worker_pid: int | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    normalized_type = _normalize_message_type(message_type)
    if not is_worker_to_main_type(normalized_type):
        raise ValueError(f"message type is not worker->main: {normalized_type}")
    return build_message(
        normalized_type,
        payload=payload,
        profile_id=profile_id,
        worker_pid=worker_pid,
        timestamp=timestamp,
    )


def parse_message(raw_message: Mapping[str, Any]) -> IPCMessage:
    if "type" not in raw_message:
        raise ValueError("ipc message is missing 'type'")

    normalized_type = _normalize_message_type(str(raw_message["type"]))
    payload = raw_message.get("payload") or {}
    if not isinstance(payload, Mapping):
        raise ValueError("ipc message payload must be a mapping")

    profile_id_value = raw_message.get("profile_id")
    if profile_id_value is not None and not isinstance(profile_id_value, str):
        raise ValueError("ipc profile_id must be a string")

    worker_pid_value = raw_message.get("worker_pid")
    if worker_pid_value is not None and not isinstance(worker_pid_value, int):
        raise ValueError("ipc worker_pid must be an int")

    timestamp_value = raw_message.get("timestamp", time.time())
    return IPCMessage(
        type=normalized_type,
        payload=dict(payload),
        profile_id=profile_id_value,
        worker_pid=worker_pid_value,
        timestamp=float(timestamp_value),
    )
