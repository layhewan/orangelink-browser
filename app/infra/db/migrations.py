from __future__ import annotations

import sqlite3

from app.infra.db.models import (
    BATCH_ITEM_STATUSES,
    BATCH_STATUSES,
    DEFAULT_MAX_PARALLEL,
    EXIT_REASONS,
    PROCESS_ROLES,
)

LATEST_DB_VERSION = 3


def migrate(conn: sqlite3.Connection, target_version: int = LATEST_DB_VERSION) -> None:
    if target_version > LATEST_DB_VERSION:
        msg = f"unsupported target_version={target_version}"
        raise ValueError(msg)

    conn.execute("PRAGMA foreign_keys = ON")
    current = get_user_version(conn)
    if current > target_version:
        msg = f"database version {current} is newer than target {target_version}"
        raise ValueError(msg)

    with conn:
        _ensure_base_tables(conn)

    if current < 2 <= target_version:
        with conn:
            _migrate_to_v2(conn)
            _set_user_version(conn, 2)
        current = 2

    if current < 3 <= target_version:
        with conn:
            _migrate_to_v3(conn)
            _set_user_version(conn, 3)


def get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


def _ensure_base_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_processes (
            id INTEGER PRIMARY KEY,
            profile_id INTEGER NOT NULL,
            worker_pid INTEGER,
            started_at TEXT,
            ended_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY,
            event_type TEXT NOT NULL,
            batch_id INTEGER,
            profile_id INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS detection_snapshots (
            id INTEGER PRIMARY KEY,
            profile_id INTEGER NOT NULL,
            batch_id INTEGER,
            batch_item_id INTEGER,
            snapshot_id TEXT,
            score_summary_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    batch_status_check = ",".join(f"'{status}'" for status in BATCH_STATUSES)
    item_status_check = ",".join(f"'{status}'" for status in BATCH_ITEM_STATUSES)

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS launch_batches (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            requested_profile_ids_json TEXT NOT NULL,
            template_id INTEGER,
            max_parallel INTEGER NOT NULL DEFAULT {DEFAULT_MAX_PARALLEL},
            status TEXT NOT NULL CHECK (status IN ({batch_status_check})),
            summary_json TEXT NOT NULL DEFAULT '{{}}'
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS batch_items (
            id INTEGER PRIMARY KEY,
            batch_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({item_status_check})),
            final_runtime_config_json TEXT NOT NULL DEFAULT '{{}}',
            worker_pid INTEGER,
            error_code TEXT,
            error_message TEXT,
            started_at TEXT,
            ended_at TEXT,
            FOREIGN KEY (batch_id) REFERENCES launch_batches(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_templates (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_items_batch_id ON batch_items(batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_processes_profile_id "
        "ON runtime_processes(profile_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_event_type ON audit_events(event_type)"
    )


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "batch_items", "final_runtime_config_json"):
        conn.execute(
            """
            ALTER TABLE batch_items
            ADD COLUMN final_runtime_config_json TEXT NOT NULL DEFAULT '{}'
            """
        )

    if not _column_exists(conn, "profiles", "allow_proxy_reuse"):
        conn.execute(
            """
            ALTER TABLE profiles
            ADD COLUMN allow_proxy_reuse INTEGER NOT NULL DEFAULT 0
            """
        )
    if not _column_exists(conn, "profiles", "profile_template_overrides_json"):
        conn.execute(
            """
            ALTER TABLE profiles
            ADD COLUMN profile_template_overrides_json TEXT
            """
        )

    if not _column_exists(conn, "runtime_processes", "batch_id"):
        conn.execute(
            """
            ALTER TABLE runtime_processes
            ADD COLUMN batch_id INTEGER
            """
        )
    if not _column_exists(conn, "runtime_processes", "process_role"):
        process_roles_check = ",".join(f"'{role}'" for role in PROCESS_ROLES)
        conn.execute(
            f"""
            ALTER TABLE runtime_processes
            ADD COLUMN process_role TEXT NOT NULL DEFAULT 'worker'
            CHECK (process_role IN ({process_roles_check}))
            """
        )
    if not _column_exists(conn, "runtime_processes", "heartbeat_at"):
        conn.execute(
            """
            ALTER TABLE runtime_processes
            ADD COLUMN heartbeat_at TEXT
            """
        )
    if not _column_exists(conn, "runtime_processes", "exit_reason"):
        exit_reasons_check = ",".join(f"'{reason}'" for reason in EXIT_REASONS)
        conn.execute(
            f"""
            ALTER TABLE runtime_processes
            ADD COLUMN exit_reason TEXT
            CHECK (exit_reason IN ({exit_reasons_check}) OR exit_reason IS NULL)
            """
        )


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)
