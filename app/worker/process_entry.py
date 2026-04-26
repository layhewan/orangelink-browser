from __future__ import annotations

import os
from multiprocessing.connection import Connection
from typing import Any

from app.worker.collector import WorkerCollectorClient
from app.worker.health import WorkerHealthReporter
from app.worker.ipc import MainToWorkerType, WorkerToMainType, build_worker_message, parse_message
from app.worker.runtime import WorkerRuntime


def worker_entry(
    profile_id: str,
    launch_config: dict[str, Any],
    command_conn: Connection,
    event_conn: Connection,
) -> None:
    pid = os.getpid()

    def send(message: dict[str, Any]) -> None:
        event_conn.send(message)

    health = WorkerHealthReporter(worker_id=profile_id, sender=send, heartbeat_interval_s=5.0)
    runtime = WorkerRuntime(launch_config)
    collector = WorkerCollectorClient(
        detection_page_url=str(launch_config.get("detection_page_url", "https://www.browserscan.net/zh")),
        scoring_api_url=str(launch_config.get("scoring_api_url", "http://127.0.0.1:8765/probe")),
    )

    try:
        send(build_worker_message(WorkerToMainType.LAUNCH_STARTED, worker_pid=pid, payload={"profile_id": profile_id}))
        runtime.launch()
        send(build_worker_message(WorkerToMainType.LAUNCH_READY, worker_pid=pid, payload={"profile_id": profile_id}))
        health.start(pid=pid, state_provider=lambda: "running")

        running = True
        while running:
            if command_conn.poll(0.5):
                raw = command_conn.recv()
                command = parse_message(raw)
                cmd = command.type

                if cmd == MainToWorkerType.PING.value:
                    health.emit_heartbeat(pid=pid, state="running")
                    continue

                if cmd == MainToWorkerType.COLLECT_SNAPSHOT.value:
                    result = collector.collect_snapshot(
                        context=runtime.context,
                        profile_id=profile_id,
                        extra_probe_payload={"worker_pid": pid},
                    )
                    snapshot_event = collector.build_snapshot_event(result=result, worker_pid=pid)
                    snapshot_event.setdefault("payload", {})
                    snapshot_event["payload"]["profile_id"] = profile_id
                    send(snapshot_event)
                    continue

                if cmd == MainToWorkerType.STOP_PROFILE.value:
                    running = False
                    continue

                if cmd == MainToWorkerType.DESTROY_PROFILE_ENV.value:
                    runtime.destroy_profile_env()
                    running = False
                    continue

        runtime.stop()
        health.stop(exit_reason="normal", pid=pid, exit_code=0)
    except Exception as exc:  # noqa: BLE001
        send(
            build_worker_message(
                WorkerToMainType.LAUNCH_FAILED,
                worker_pid=pid,
                payload={"error_code": "LAUNCH_ERROR", "error_message": str(exc)},
            )
        )
        health.stop(exit_reason="crash", pid=pid, exit_code=1, extra={"error_message": str(exc)})
