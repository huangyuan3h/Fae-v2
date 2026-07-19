"""SQLite persistence for schedules, push subs, prefs, and notification inbox."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class StoredJob:
    id: str
    kind: str  # cron | date | interval | builtin
    title: str
    body: str
    cron: str | None
    run_at: float | None
    enabled: bool
    builtin: bool
    meta: dict[str, Any]
    created_at: float
    updated_at: float


@dataclass
class NotificationPrefs:
    enabled: bool = True
    quiet_start_hour: int | None = None  # inclusive, local hour 0-23
    quiet_end_hour: int | None = None  # exclusive
    desktop_enabled: bool = True
    web_push_enabled: bool = True


@dataclass
class InboxItem:
    id: str
    title: str
    body: str
    session_id: str
    created_at: float
    read: bool
    source: str


@dataclass
class PushSubscription:
    endpoint: str
    p256dh: str
    auth: str
    created_at: float


class ScheduleStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  title TEXT NOT NULL,
                  body TEXT NOT NULL DEFAULT '',
                  cron TEXT,
                  run_at REAL,
                  enabled INTEGER NOT NULL DEFAULT 1,
                  builtin INTEGER NOT NULL DEFAULT 0,
                  meta_json TEXT NOT NULL DEFAULT '{}',
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                  endpoint TEXT PRIMARY KEY,
                  p256dh TEXT NOT NULL,
                  auth TEXT NOT NULL,
                  created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_prefs (
                  id INTEGER PRIMARY KEY CHECK (id = 1),
                  enabled INTEGER NOT NULL DEFAULT 1,
                  quiet_start_hour INTEGER,
                  quiet_end_hour INTEGER,
                  desktop_enabled INTEGER NOT NULL DEFAULT 1,
                  web_push_enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS notification_inbox (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  body TEXT NOT NULL,
                  session_id TEXT NOT NULL DEFAULT '',
                  created_at REAL NOT NULL,
                  read INTEGER NOT NULL DEFAULT 0,
                  source TEXT NOT NULL DEFAULT 'system'
                );
                INSERT OR IGNORE INTO notification_prefs (id) VALUES (1);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── Jobs ──────────────────────────────────────────────────────────

    def upsert_job(self, job: StoredJob) -> StoredJob:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (
                  id, kind, title, body, cron, run_at, enabled, builtin,
                  meta_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  kind=excluded.kind,
                  title=excluded.title,
                  body=excluded.body,
                  cron=excluded.cron,
                  run_at=excluded.run_at,
                  enabled=excluded.enabled,
                  builtin=excluded.builtin,
                  meta_json=excluded.meta_json,
                  updated_at=excluded.updated_at
                """,
                (
                    job.id,
                    job.kind,
                    job.title,
                    job.body,
                    job.cron,
                    job.run_at,
                    1 if job.enabled else 0,
                    1 if job.builtin else 0,
                    json.dumps(job.meta),
                    job.created_at,
                    job.updated_at,
                ),
            )
            self._conn.commit()
        return job

    def get_job(self, job_id: str) -> StoredJob | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self) -> list[StoredJob]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY builtin DESC, created_at ASC"
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def patch_job(
        self,
        job_id: str,
        *,
        enabled: bool | None = None,
        title: str | None = None,
        body: str | None = None,
        cron: str | None = None,
        run_at: float | None = None,
        clear_run_at: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> StoredJob | None:
        job = self.get_job(job_id)
        if job is None:
            return None
        now = time.time()
        if enabled is not None:
            job.enabled = enabled
        if title is not None:
            job.title = title
        if body is not None:
            job.body = body
        if cron is not None:
            job.cron = cron
        if clear_run_at:
            job.run_at = None
        elif run_at is not None:
            job.run_at = run_at
        if meta is not None:
            job.meta = meta
        job.updated_at = now
        return self.upsert_job(job)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> StoredJob:
        meta_raw = row["meta_json"] or "{}"
        try:
            meta = json.loads(meta_raw)
        except json.JSONDecodeError:
            meta = {}
        return StoredJob(
            id=row["id"],
            kind=row["kind"],
            title=row["title"],
            body=row["body"] or "",
            cron=row["cron"],
            run_at=row["run_at"],
            enabled=bool(row["enabled"]),
            builtin=bool(row["builtin"]),
            meta=meta if isinstance(meta, dict) else {},
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def ensure_builtin_jobs(
        self, specs: list[tuple[str, str, str | None, str, dict[str, Any]]]
    ) -> None:
        """Ensure builtin job rows exist. specs: id, kind, cron, title, meta."""
        now = time.time()
        for job_id, kind, cron, title, meta in specs:
            existing = self.get_job(job_id)
            if existing is not None:
                continue
            self.upsert_job(
                StoredJob(
                    id=job_id,
                    kind=kind,
                    title=title,
                    body="",
                    cron=cron,
                    run_at=None,
                    enabled=True,
                    builtin=True,
                    meta=meta,
                    created_at=now,
                    updated_at=now,
                )
            )

    # ── Prefs ─────────────────────────────────────────────────────────

    def get_prefs(self) -> NotificationPrefs:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM notification_prefs WHERE id = 1"
            ).fetchone()
        if row is None:
            return NotificationPrefs()
        return NotificationPrefs(
            enabled=bool(row["enabled"]),
            quiet_start_hour=row["quiet_start_hour"],
            quiet_end_hour=row["quiet_end_hour"],
            desktop_enabled=bool(row["desktop_enabled"]),
            web_push_enabled=bool(row["web_push_enabled"]),
        )

    def set_prefs(self, prefs: NotificationPrefs) -> NotificationPrefs:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO notification_prefs (
                  id, enabled, quiet_start_hour, quiet_end_hour,
                  desktop_enabled, web_push_enabled
                ) VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  enabled=excluded.enabled,
                  quiet_start_hour=excluded.quiet_start_hour,
                  quiet_end_hour=excluded.quiet_end_hour,
                  desktop_enabled=excluded.desktop_enabled,
                  web_push_enabled=excluded.web_push_enabled
                """,
                (
                    1 if prefs.enabled else 0,
                    prefs.quiet_start_hour,
                    prefs.quiet_end_hour,
                    1 if prefs.desktop_enabled else 0,
                    1 if prefs.web_push_enabled else 0,
                ),
            )
            self._conn.commit()
        return prefs

    # ── Push ──────────────────────────────────────────────────────────

    def add_push_subscription(
        self, endpoint: str, p256dh: str, auth: str
    ) -> PushSubscription:
        sub = PushSubscription(
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            created_at=time.time(),
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                  p256dh=excluded.p256dh,
                  auth=excluded.auth
                """,
                (sub.endpoint, sub.p256dh, sub.auth, sub.created_at),
            )
            self._conn.commit()
        return sub

    def remove_push_subscription(self, endpoint: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_push_subscriptions(self) -> list[PushSubscription]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM push_subscriptions"
            ).fetchall()
        return [
            PushSubscription(
                endpoint=r["endpoint"],
                p256dh=r["p256dh"],
                auth=r["auth"],
                created_at=float(r["created_at"]),
            )
            for r in rows
        ]

    # ── Inbox ─────────────────────────────────────────────────────────

    def add_inbox(
        self,
        title: str,
        body: str,
        *,
        session_id: str = "",
        source: str = "system",
    ) -> InboxItem:
        item = InboxItem(
            id=str(uuid.uuid4()),
            title=title,
            body=body,
            session_id=session_id,
            created_at=time.time(),
            read=False,
            source=source,
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO notification_inbox (
                  id, title, body, session_id, created_at, read, source
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    item.id,
                    item.title,
                    item.body,
                    item.session_id,
                    item.created_at,
                    item.source,
                ),
            )
            self._conn.commit()
        return item

    def list_inbox(self, *, limit: int = 50, unread_only: bool = False) -> list[InboxItem]:
        q = "SELECT * FROM notification_inbox"
        if unread_only:
            q += " WHERE read = 0"
        q += " ORDER BY created_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, (limit,)).fetchall()
        return [
            InboxItem(
                id=r["id"],
                title=r["title"],
                body=r["body"],
                session_id=r["session_id"] or "",
                created_at=float(r["created_at"]),
                read=bool(r["read"]),
                source=r["source"] or "system",
            )
            for r in rows
        ]

    def mark_read(self, ids: list[str] | None = None) -> int:
        with self._lock:
            if ids:
                placeholders = ",".join("?" * len(ids))
                cur = self._conn.execute(
                    f"UPDATE notification_inbox SET read = 1 WHERE id IN ({placeholders})",
                    ids,
                )
            else:
                cur = self._conn.execute(
                    "UPDATE notification_inbox SET read = 1 WHERE read = 0"
                )
            self._conn.commit()
            return cur.rowcount

    def create_custom_job(
        self,
        *,
        kind: str,
        title: str,
        body: str = "",
        cron: str | None = None,
        run_at: float | None = None,
        meta: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> StoredJob:
        now = time.time()
        job = StoredJob(
            id=job_id or str(uuid.uuid4()),
            kind=kind,
            title=title,
            body=body,
            cron=cron,
            run_at=run_at,
            enabled=True,
            builtin=False,
            meta=meta or {},
            created_at=now,
            updated_at=now,
        )
        return self.upsert_job(job)
