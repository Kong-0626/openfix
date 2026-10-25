"""SQLite persistence for work orders and audit events."""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkOrderStore:
    """Persistence layer with small, explicit transactions.

    This is intentionally SQLite-based so the prototype does not require an
    external database. Authentication and authorization are demo-only and must
    be replaced by the host organization's identity provider in production.
    """

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_orders (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    asset_id TEXT,
                    priority TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    diagnosis_id TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approver TEXT,
                    approved_at TEXT,
                    rejection_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )

    def create_work_order(
        self,
        *,
        asset_id: str | None,
        priority: str,
        title: str,
        summary: str,
        diagnosis_id: str,
        actions: list[dict],
        evidence_ids: list[str],
        actor: str,
    ) -> dict:
        now = _now()
        work_order_id = f"WO-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO work_orders (
                    id, created_at, updated_at, asset_id, priority, title, summary,
                    diagnosis_id, actions_json, evidence_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval')
                """,
                (
                    work_order_id,
                    now,
                    now,
                    asset_id,
                    priority,
                    title,
                    summary,
                    diagnosis_id,
                    json.dumps(actions, ensure_ascii=False),
                    json.dumps(evidence_ids, ensure_ascii=False),
                ),
            )
            self._append_audit(
                connection,
                action="work_order.created",
                actor=actor,
                object_id=work_order_id,
                details={"status": "pending_approval", "diagnosis_id": diagnosis_id},
            )
        return self.get_work_order(work_order_id)  # type: ignore[return-value]

    def list_work_orders(self, limit: int = 20) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM work_orders ORDER BY created_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_work_order(self, work_order_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM work_orders WHERE id = ?", (work_order_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def approve_work_order(
        self, work_order_id: str, approver: str, confirmation: str
    ) -> dict | None:
        now = _now()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM work_orders WHERE id = ?", (work_order_id,)
            ).fetchone()
            if not row:
                return None
            if row["status"] != "pending_approval":
                raise ValueError("该工单当前状态不可审批")
            cursor = connection.execute(
                """
                UPDATE work_orders
                SET status = 'approved', approver = ?, approved_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending_approval'
                """,
                (approver, now, now, work_order_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("该工单已被其他审批人处理")
            self._append_audit(
                connection,
                action="work_order.approved",
                actor=approver,
                object_id=work_order_id,
                details={"confirmation": confirmation, "status": "approved"},
            )
        return self.get_work_order(work_order_id)

    def reject_work_order(
        self, work_order_id: str, approver: str, reason: str
    ) -> dict | None:
        now = _now()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM work_orders WHERE id = ?", (work_order_id,)
            ).fetchone()
            if not row:
                return None
            if row["status"] != "pending_approval":
                raise ValueError("该工单当前状态不可驳回")
            cursor = connection.execute(
                """
                UPDATE work_orders
                SET status = 'rejected', approver = ?, rejection_reason = ?, updated_at = ?
                WHERE id = ? AND status = 'pending_approval'
                """,
                (approver, reason, now, work_order_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("该工单已被其他审批人处理")
            self._append_audit(
                connection,
                action="work_order.rejected",
                actor=approver,
                object_id=work_order_id,
                details={"reason": reason, "status": "rejected"},
            )
        return self.get_work_order(work_order_id)

    def list_audit_events(self, limit: int = 30) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "action": row["action"],
                "actor": row["actor"],
                "object_type": row["object_type"],
                "object_id": row["object_id"],
                "details": json.loads(row["details_json"]),
            }
            for row in rows
        ]

    def _append_audit(
        self,
        connection: sqlite3.Connection,
        *,
        action: str,
        actor: str,
        object_id: str,
        details: dict,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (
                created_at, action, actor, object_type, object_id, details_json
            ) VALUES (?, ?, ?, 'work_order', ?, ?)
            """,
            (
                _now(),
                action,
                actor,
                object_id,
                json.dumps(details, ensure_ascii=False),
            ),
        )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "asset_id": row["asset_id"],
            "priority": row["priority"],
            "title": row["title"],
            "summary": row["summary"],
            "diagnosis_id": row["diagnosis_id"],
            "actions": json.loads(row["actions_json"]),
            "evidence_ids": json.loads(row["evidence_json"]),
            "status": row["status"],
            "approver": row["approver"],
            "approved_at": row["approved_at"],
            "rejection_reason": row["rejection_reason"],
        }
