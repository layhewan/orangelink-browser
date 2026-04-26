from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infra.db.migrations import migrate
from app.infra.db.models import DEFAULT_MAX_PARALLEL

_UNSET = object()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DbRepository:
    def __init__(self, conn: sqlite3.Connection, *, auto_migrate: bool = True) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        if auto_migrate:
            migrate(self._conn)

    def close(self) -> None:
        self._conn.close()

    def create_batch(
        self,
        requested_profile_ids: list[int],
        *,
        template_id: int | None = None,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        status: str = "pending",
        summary: dict[str, Any] | None = None,
    ) -> int:
        created_at = _utc_now_iso()
        requested_ids_json = json.dumps(requested_profile_ids, separators=(",", ":"))
        summary_json = json.dumps(summary or {}, separators=(",", ":"))

        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO launch_batches (
                    created_at,
                    requested_profile_ids_json,
                    template_id,
                    max_parallel,
                    status,
                    summary_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    requested_ids_json,
                    template_id,
                    max_parallel,
                    status,
                    summary_json,
                ),
            )
            batch_id = int(cursor.lastrowid)
            self._conn.executemany(
                """
                INSERT INTO batch_items (
                    batch_id,
                    profile_id,
                    status,
                    final_runtime_config_json
                ) VALUES (?, ?, ?, ?)
                """,
                [(batch_id, profile_id, "pending", "{}") for profile_id in requested_profile_ids],
            )
        return batch_id

    @classmethod
    def open(cls, db_path: str | Path, *, auto_migrate: bool = True) -> "DbRepository":
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        return cls(conn, auto_migrate=auto_migrate)

    def create_launch_batch(
        self,
        *,
        profile_ids: list[int],
        template_id: int | None,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
    ) -> dict[str, Any]:
        created_at = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO launch_batches (
                    created_at,
                    requested_profile_ids_json,
                    template_id,
                    max_parallel,
                    status,
                    summary_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    json.dumps(profile_ids, separators=(",", ":")),
                    template_id,
                    max_parallel,
                    "pending",
                    "{}",
                ),
            )
        batch_id = int(cur.lastrowid)
        row = self._conn.execute("SELECT * FROM launch_batches WHERE id = ?", (batch_id,)).fetchone()
        return dict(row)

    def finalize_launch_batch(self, *, batch_id: int, status: str, summary_json: dict[str, Any]) -> None:
        self.update_batch_status(batch_id=batch_id, status=status, summary_json=summary_json)

    def update_batch_status(self, *, batch_id: int, status: str, summary_json: dict[str, Any] | None = None) -> None:
        params: list[Any] = [status]
        assignments = ["status = ?"]
        if summary_json is not None:
            assignments.append("summary_json = ?")
            params.append(json.dumps(summary_json, separators=(",", ":")))
        params.append(batch_id)
        sql = f"UPDATE launch_batches SET {', '.join(assignments)} WHERE id = ?"
        with self._conn:
            self._conn.execute(sql, params)

    def create_batch_item(
        self,
        *,
        batch_id: int,
        profile_id: int,
        status: str,
        error_message: str | None = None,
        error_code: str | None = None,
        worker_pid: int | None = None,
        final_runtime_config_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO batch_items (
                    batch_id, profile_id, status, final_runtime_config_json,
                    worker_pid, error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    profile_id,
                    status,
                    json.dumps(final_runtime_config_json or {}, separators=(",", ":")),
                    worker_pid,
                    error_code,
                    error_message,
                ),
            )
        item_id = int(cur.lastrowid)
        row = self._conn.execute("SELECT * FROM batch_items WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_batch_item_dict(row)

    def list_batch_items(self, batch_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM batch_items WHERE batch_id = ? ORDER BY id",
            (batch_id,),
        ).fetchall()
        return [self._row_to_batch_item_dict(row) for row in rows]

    def get_batch_item_by_worker_pid(self, worker_pid: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT * FROM batch_items
            WHERE worker_pid = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (worker_pid,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_batch_item_dict(row)

    def get_open_batch_item_by_profile(self, profile_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT * FROM batch_items
            WHERE profile_id = ? AND status IN ('launching', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_batch_item_dict(row)

    def get_launch_batch(self, batch_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM launch_batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["requested_profile_ids_json"] = json.loads(item.get("requested_profile_ids_json") or "[]")
        item["summary_json"] = json.loads(item.get("summary_json") or "{}")
        return item

    def list_launch_batches(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM launch_batches ORDER BY id DESC").fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["requested_profile_ids_json"] = json.loads(item.get("requested_profile_ids_json") or "[]")
            item["summary_json"] = json.loads(item.get("summary_json") or "{}")
            out.append(item)
        return out

    def update_batch_item_status(
        self,
        *,
        batch_item_id: int | None = None,
        item_id: int | None = None,
        status: str,
        worker_pid: int | None | object = _UNSET,
        error_code: str | None | object = _UNSET,
        error_message: str | None | object = _UNSET,
        started_at: str | None | object = _UNSET,
        ended_at: str | None | object = _UNSET,
        final_runtime_config_json: dict[str, Any] | object = _UNSET,
    ) -> None:
        target_id = batch_item_id if batch_item_id is not None else item_id
        if target_id is None:
            raise ValueError("batch_item_id or item_id is required")

        assignments: list[str] = ["status = ?"]
        values: list[Any] = [status]

        if worker_pid is not _UNSET:
            assignments.append("worker_pid = ?")
            values.append(worker_pid)
        if error_code is not _UNSET:
            assignments.append("error_code = ?")
            values.append(error_code)
        if error_message is not _UNSET:
            assignments.append("error_message = ?")
            values.append(error_message)
        if started_at is not _UNSET:
            assignments.append("started_at = ?")
            values.append(started_at)
        if ended_at is not _UNSET:
            assignments.append("ended_at = ?")
            values.append(ended_at)
        if final_runtime_config_json is not _UNSET:
            assignments.append("final_runtime_config_json = ?")
            values.append(json.dumps(final_runtime_config_json, separators=(",", ":")))

        values.append(target_id)
        sql = f"UPDATE batch_items SET {', '.join(assignments)} WHERE id = ?"
        with self._conn:
            self._conn.execute(sql, values)

    def record_runtime_process(
        self,
        *,
        profile_id: int,
        worker_pid: int | None,
        batch_id: int | None = None,
        process_role: str = "worker",
        heartbeat_at: str | None = None,
        exit_reason: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> int:
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO runtime_processes (
                    profile_id,
                    worker_pid,
                    batch_id,
                    process_role,
                    heartbeat_at,
                    exit_reason,
                    started_at,
                    ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    worker_pid,
                    batch_id,
                    process_role,
                    heartbeat_at,
                    exit_reason,
                    started_at or _utc_now_iso(),
                    ended_at,
                ),
            )
        return int(cursor.lastrowid)

    def update_runtime_process_heartbeat(self, *, worker_pid: int, heartbeat_at: str) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE runtime_processes
                SET heartbeat_at = ?
                WHERE id = (
                    SELECT id FROM runtime_processes
                    WHERE worker_pid = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (heartbeat_at, worker_pid),
            )

    def mark_runtime_process_exit(
        self,
        *,
        worker_pid: int,
        exit_reason: str,
        ended_at: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE runtime_processes
                SET exit_reason = ?, ended_at = ?
                WHERE id = (
                    SELECT id FROM runtime_processes
                    WHERE worker_pid = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (exit_reason, ended_at or _utc_now_iso(), worker_pid),
            )

    def write_audit_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        batch_id: int | None = None,
        profile_id: int | None = None,
        created_at: str | None = None,
    ) -> int:
        payload_json = json.dumps(payload or {}, separators=(",", ":"))
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO audit_events (
                    event_type,
                    batch_id,
                    profile_id,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    batch_id,
                    profile_id,
                    payload_json,
                    created_at or _utc_now_iso(),
                ),
            )
        return int(cursor.lastrowid)

    def record_audit_event(
        self,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        batch_id: int | None = None,
        profile_id: int | None = None,
    ) -> int:
        return self.write_audit_event(
            event_type=event_type,
            payload=payload,
            batch_id=batch_id,
            profile_id=profile_id,
        )

    def ensure_seed_data(self) -> None:
        with self._conn:
            count = self._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            if count == 0:
                self._conn.executemany(
                    """
                    INSERT INTO profiles (id, name, allow_proxy_reuse, profile_template_overrides_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (1, "profile-1", 0, "{}"),
                        (2, "profile-2", 0, "{}"),
                        (3, "profile-3", 1, "{}"),
                    ],
                )

            template_count = self._conn.execute("SELECT COUNT(*) FROM profile_templates").fetchone()[0]
            if template_count == 0:
                now = _utc_now_iso()
                self._conn.execute(
                    """
                    INSERT INTO profile_templates (name, description, config_json, created_at, updated_at, enabled)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "default-template",
                        "default runtime template",
                        json.dumps(
                            {
                                "proxy": {"proxy_host": "127.0.0.1", "proxy_port": 7897, "scheme": "http"},
                                "browser": {"locale": "en-US"},
                            },
                            separators=(",", ":"),
                        ),
                        now,
                        now,
                        1,
                    ),
                )

    def create_profile(
        self,
        *,
        name: str,
        allow_proxy_reuse: bool = False,
        profile_template_overrides_json: dict[str, Any] | None = None,
    ) -> int:
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO profiles (name, allow_proxy_reuse, profile_template_overrides_json)
                VALUES (?, ?, ?)
                """,
                (
                    name,
                    1 if allow_proxy_reuse else 0,
                    json.dumps(profile_template_overrides_json or {}, separators=(",", ":")),
                ),
            )
        return int(cur.lastrowid)

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM profiles ORDER BY id").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["allow_proxy_reuse"] = bool(item.get("allow_proxy_reuse", 0))
            item["profile_template_overrides_json"] = json.loads(item.get("profile_template_overrides_json") or "{}")
            output.append(item)
        return output

    def get_profiles(self, profile_ids: list[int]) -> list[dict[str, Any]]:
        if not profile_ids:
            return []
        placeholders = ",".join("?" for _ in profile_ids)
        rows = self._conn.execute(
            f"SELECT * FROM profiles WHERE id IN ({placeholders})",
            profile_ids,
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["allow_proxy_reuse"] = bool(item.get("allow_proxy_reuse", 0))
            item["profile_template_overrides_json"] = json.loads(item.get("profile_template_overrides_json") or "{}")
            result.append(item)
        return result

    def create_profile_template(
        self,
        *,
        name: str,
        description: str | None,
        config_json: dict[str, Any],
        enabled: bool = True,
    ) -> int:
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO profile_templates (name, description, config_json, created_at, updated_at, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, description, json.dumps(config_json, separators=(",", ":")), now, now, 1 if enabled else 0),
            )
        return int(cur.lastrowid)

    def list_profile_templates(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM profile_templates WHERE enabled = 1 ORDER BY id").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["config_json"] = json.loads(item.get("config_json") or "{}")
            item["enabled"] = bool(item.get("enabled", 0))
            result.append(item)
        return result

    def get_profile_template(self, template_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM profile_templates WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["config_json"] = json.loads(item.get("config_json") or "{}")
        item["enabled"] = bool(item.get("enabled", 0))
        return item

    def get_system_defaults(self) -> dict[str, Any]:
        return {
            "proxy": {"proxy_host": "127.0.0.1", "proxy_port": 7897, "scheme": "http"},
            "browser": {"headless": False, "start_url": "about:blank", "locale": "en-US"},
        }

    def get_active_proxy_keys(self) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT final_runtime_config_json
            FROM batch_items
            WHERE status IN ('running', 'launching')
            """
        ).fetchall()
        keys: list[str] = []
        for row in rows:
            raw = row["final_runtime_config_json"] or "{}"
            try:
                cfg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            proxy = cfg.get("proxy") if isinstance(cfg, dict) else None
            if isinstance(proxy, dict):
                host = proxy.get("proxy_host")
                port = proxy.get("proxy_port")
                scheme = proxy.get("scheme", "http")
                if host and port:
                    keys.append(f"{scheme}://{host}:{port}")
        return keys

    def record_detection_snapshot(
        self,
        *,
        profile_id: int,
        snapshot_id: str | None,
        score_summary: dict[str, Any],
        batch_id: int | None = None,
        batch_item_id: int | None = None,
    ) -> int:
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO detection_snapshots (
                    profile_id, batch_id, batch_item_id, snapshot_id, score_summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    batch_id,
                    batch_item_id,
                    snapshot_id,
                    json.dumps(score_summary, separators=(",", ":")),
                    _utc_now_iso(),
                ),
            )
        return int(cur.lastrowid)

    def list_detection_snapshots(self, profile_id: int | None = None) -> list[dict[str, Any]]:
        if profile_id is None:
            rows = self._conn.execute("SELECT * FROM detection_snapshots ORDER BY id DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM detection_snapshots WHERE profile_id = ? ORDER BY id DESC",
                (profile_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["score_summary_json"] = json.loads(item.get("score_summary_json") or "{}")
            result.append(item)
        return result

    @staticmethod
    def _row_to_batch_item_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["final_runtime_config_json"] = json.loads(item.get("final_runtime_config_json") or "{}")
        return item
