from __future__ import annotations

from typing import Final, Literal

DEFAULT_MAX_PARALLEL: Final[int] = 5

BatchStatus = Literal["pending", "running", "partial_success", "completed", "failed"]
BatchItemStatus = Literal[
    "pending",
    "launching",
    "running",
    "failed",
    "skipped",
    "stopped",
]
ProcessRole = Literal["worker"]
ExitReason = Literal["normal", "crash", "killed", "timeout"]

BATCH_STATUSES: Final[tuple[str, ...]] = (
    "pending",
    "running",
    "partial_success",
    "completed",
    "failed",
)
BATCH_ITEM_STATUSES: Final[tuple[str, ...]] = (
    "pending",
    "launching",
    "running",
    "failed",
    "skipped",
    "stopped",
)
PROCESS_ROLES: Final[tuple[str, ...]] = ("worker",)
EXIT_REASONS: Final[tuple[str, ...]] = ("normal", "crash", "killed", "timeout")

AUDIT_EVENT_TYPES: Final[tuple[str, ...]] = (
    "batch_launch_requested",
    "batch_item_skipped_proxy_failure",
    "batch_item_skipped_proxy_reuse_conflict",
    "worker_crashed",
    "batch_completed_partial_success",
)
