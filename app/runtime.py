from __future__ import annotations

from datetime import UTC, datetime
import logging
import threading
import time
from typing import Any

from app.core import events
from app.core.config import Settings, get_settings
from app.core.resource_governor import ResourceGovernor
from app.core.template_resolver import TemplateResolver
from app.core.proxy_reuse_guard import ProxyReuseGuard
from app.infra.db.repository import DbRepository
from app.supervisor.batch_launch_coordinator import BatchLaunchCoordinator
from app.supervisor.worker_process_manager import WorkerProcessManager
from app.worker.ipc import MainToWorkerType, build_main_message

logger = logging.getLogger(__name__)


class AppRuntime:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.repository = DbRepository.open(self.settings.db_file)
        self.repository.ensure_seed_data()

        self.worker_manager = WorkerProcessManager()
        self.coordinator = BatchLaunchCoordinator(
            repository=self.repository,
            template_resolver=TemplateResolver(),
            proxy_reuse_guard=ProxyReuseGuard(),
            resource_governor=ResourceGovernor(max_concurrency=self.settings.max_parallel_workers),
            worker_manager=self.worker_manager,
            max_parallel=self.settings.max_parallel_workers,
            detection_api_url=f"http://{self.settings.gui_host}:{self.settings.gui_port}/detection/probe",
        )

        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2.0)
        self._monitor_thread = None
        for profile in self.worker_manager.active_profile_ids():
            self.worker_manager.reap(profile, force=True)
        self.repository.close()

    def launch_batch(self, profile_ids: list[int], template_id: int | None = None) -> dict[str, Any]:
        return self.coordinator.launch_batch(profile_ids=profile_ids, template_id=template_id)

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = self.repository.get_launch_batch(batch_id)
        if batch is None:
            return None
        items = self.repository.list_batch_items(batch_id)
        return {"batch": batch, "items": items}

    def stop_profile(self, profile_id: str) -> bool:
        sent = self.worker_manager.send_command(
            profile_id,
            build_main_message(MainToWorkerType.STOP_PROFILE, payload={"profile_id": profile_id}),
        )
        if sent:
            self.worker_manager.mark_stopping(profile_id)
        return sent

    def collect_snapshot(self, profile_id: str) -> bool:
        return self.worker_manager.send_command(
            profile_id,
            build_main_message(MainToWorkerType.COLLECT_SNAPSHOT, payload={"profile_id": profile_id}),
        )

    def destroy_profile_env(self, profile_id: str) -> bool:
        sent = self.worker_manager.send_command(
            profile_id,
            build_main_message(MainToWorkerType.DESTROY_PROFILE_ENV, payload={"profile_id": profile_id}),
        )
        if sent:
            self.worker_manager.mark_stopping(profile_id)
        return sent

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                worker_events = self.worker_manager.poll_worker_events()
                self._persist_worker_events(worker_events)

                transitioned = self.worker_manager.monitor()
                self._persist_transitioned_records(transitioned)

                running_batches = [
                    b for b in self.repository.list_launch_batches() if b.get("status") in {"pending", "running"}
                ]
                for batch in running_batches:
                    batch_id = int(batch["id"])
                    self.coordinator.dispatch_pending(batch_id)
                    self.coordinator.finalize_batch(batch_id)

                for profile_id in self.worker_manager.active_profile_ids():
                    self.worker_manager.send_command(profile_id, build_main_message(MainToWorkerType.PING, payload={}))
            except Exception:  # noqa: BLE001
                logger.exception("monitor loop iteration failed")
            time.sleep(1.0)

    def _persist_worker_events(self, worker_events: list[dict[str, Any]]) -> None:
        for event in worker_events:
            event_type = event.get("type")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            worker_pid = event.get("worker_pid") if isinstance(event.get("worker_pid"), int) else None

            if event_type == "launch_ready":
                if worker_pid is not None:
                    item = self.repository.get_batch_item_by_worker_pid(worker_pid)
                    if item is not None:
                        self.repository.update_batch_item_status(
                            batch_item_id=item["id"],
                            status="running",
                            started_at=_utc_now_iso(),
                        )
                continue

            if event_type == "launch_failed":
                if worker_pid is not None:
                    item = self.repository.get_batch_item_by_worker_pid(worker_pid)
                    if item is not None:
                        self.repository.update_batch_item_status(
                            batch_item_id=item["id"],
                            status="failed",
                            error_code=payload.get("error_code"),
                            error_message=payload.get("error_message"),
                            ended_at=_utc_now_iso(),
                        )
                        self.repository.mark_runtime_process_exit(
                            worker_pid=worker_pid,
                            exit_reason="crash",
                            ended_at=_utc_now_iso(),
                        )
                continue

            if event_type == "health_report":
                if worker_pid is not None:
                    heartbeat_raw = payload.get("heartbeat_at")
                    heartbeat_iso = _utc_now_iso()
                    if isinstance(heartbeat_raw, (int, float)):
                        heartbeat_iso = datetime.fromtimestamp(float(heartbeat_raw), tz=UTC).isoformat()
                    self.repository.update_runtime_process_heartbeat(worker_pid=worker_pid, heartbeat_at=heartbeat_iso)
                continue

            if event_type == "snapshot_collected":
                profile_raw = payload.get("profile_id")
                try:
                    profile_id = int(profile_raw) if profile_raw is not None else None
                except (TypeError, ValueError):
                    profile_id = None
                if profile_id is None:
                    worker_pid = event.get("worker_pid")
                    if isinstance(worker_pid, int):
                        mapped_profile = self.worker_manager.profile_for_pid(worker_pid)
                        if mapped_profile is not None:
                            try:
                                profile_id = int(mapped_profile)
                            except ValueError:
                                profile_id = None
                if profile_id is None:
                    continue
                batch_item_id = None
                batch_id = None
                if worker_pid is not None:
                    item = self.repository.get_batch_item_by_worker_pid(worker_pid)
                    if item is not None:
                        batch_item_id = item["id"]
                        batch_id = item["batch_id"]
                self.repository.record_detection_snapshot(
                    profile_id=profile_id,
                    batch_id=batch_id,
                    batch_item_id=batch_item_id,
                    snapshot_id=payload.get("snapshot_id"),
                    score_summary=payload.get("score_summary") or {},
                )
                continue

            if event_type == "worker_exited":
                reason = payload.get("exit_reason")
                normalized_reason = str(reason).lower()
                status = "stopped" if normalized_reason in {"normal", "killed", "timeout", "stopped"} else "failed"
                if worker_pid is not None:
                    item = self.repository.get_batch_item_by_worker_pid(worker_pid)
                    if item is not None:
                        self.repository.update_batch_item_status(
                            batch_item_id=item["id"],
                            status=status,
                            ended_at=_utc_now_iso(),
                            error_message=payload.get("error_message"),
                        )
                    self.repository.mark_runtime_process_exit(
                        worker_pid=worker_pid,
                        exit_reason=_normalize_exit_reason(normalized_reason),
                        ended_at=_utc_now_iso(),
                    )
                if str(reason).lower() in {"crash", "crashed"}:
                    self.repository.record_audit_event(
                        events.WORKER_CRASHED,
                        payload={"event": event},
                    )

    def _persist_transitioned_records(self, transitioned: list[Any]) -> None:
        for record in transitioned:
            item = self.repository.get_batch_item_by_worker_pid(record.pid)
            if item is not None:
                status = "failed" if str(record.state.value) in {"crashed", "failed"} else "stopped"
                self.repository.update_batch_item_status(
                    batch_item_id=item["id"],
                    status=status,
                    ended_at=_utc_now_iso(),
                    error_message=record.error_message,
                )
            if record.exit_reason:
                self.repository.mark_runtime_process_exit(
                    worker_pid=record.pid,
                    exit_reason=_normalize_exit_reason(record.exit_reason),
                    ended_at=_utc_now_iso(),
                )


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_exit_reason(reason: str | None) -> str:
    normalized = str(reason or "").strip().lower()
    if normalized in {"normal", "crash", "killed", "timeout"}:
        return normalized
    if normalized in {"launch_failed", "failed", "crashed"}:
        return "crash"
    return "normal"
