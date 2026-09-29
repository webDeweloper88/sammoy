from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.common.security import new_pairing_token, token_hash


class PairingStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS telegram_owner (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    telegram_user_id INTEGER NOT NULL,
                    telegram_username TEXT,
                    telegram_first_name TEXT,
                    paired_at TEXT NOT NULL,
                    revoked_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS pairing_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT 'local'
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    telegram_user_id INTEGER,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS notification_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_token(self, ttl_minutes: int, created_by: str = "local") -> tuple[str, datetime]:
        raw = new_pairing_token()
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=ttl_minutes)
        with self.connect() as conn:
            conn.execute("DELETE FROM pairing_tokens WHERE used_at IS NULL")
            conn.execute(
                "INSERT INTO pairing_tokens(token_hash, created_at, expires_at, created_by) VALUES (?, ?, ?, ?)",
                (token_hash(raw), now.isoformat(), expires.isoformat(), created_by),
            )
            self._audit(conn, None, "pairing_create", "ok", created_by)
        return raw, expires

    def claim(self, raw: str, user_id: int, username: str | None, first_name: str | None) -> bool:
        now = datetime.now(UTC)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM pairing_tokens WHERE token_hash = ?", (token_hash(raw),)
            ).fetchone()
            if not row:
                self._audit(conn, user_id, "pairing_claim", "invalid")
                return False
            conn.execute("UPDATE pairing_tokens SET attempt_count = attempt_count + 1 WHERE id = ?", (row["id"],))
            if row["used_at"] or datetime.fromisoformat(row["expires_at"]) <= now or row["attempt_count"] >= 5:
                self._audit(conn, user_id, "pairing_claim", "rejected")
                return False
            existing = conn.execute(
                "SELECT telegram_user_id FROM telegram_owner WHERE id = 1 AND is_active = 1"
            ).fetchone()
            if existing:
                self._audit(conn, user_id, "pairing_claim", "owner_exists")
                return False
            conn.execute(
                """
                INSERT INTO telegram_owner(id, telegram_user_id, telegram_username, telegram_first_name, paired_at, is_active)
                VALUES (1, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET telegram_user_id=excluded.telegram_user_id,
                    telegram_username=excluded.telegram_username, telegram_first_name=excluded.telegram_first_name,
                    paired_at=excluded.paired_at, revoked_at=NULL, is_active=1
                """,
                (user_id, username, first_name, now.isoformat()),
            )
            conn.execute("UPDATE pairing_tokens SET used_at = ? WHERE id = ?", (now.isoformat(), row["id"]))
            self._audit(conn, user_id, "pairing_claim", "ok")
            return True

    def is_owner(self, user_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM telegram_owner WHERE id = 1 AND telegram_user_id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            return row is not None

    def owner(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM telegram_owner WHERE id = 1 AND is_active = 1").fetchone()

    def reset_owner(self) -> bool:
        now = datetime.now(UTC).isoformat()
        with self.connect() as conn:
            changed = conn.execute(
                "UPDATE telegram_owner SET is_active = 0, revoked_at = ? WHERE id = 1 AND is_active = 1", (now,)
            ).rowcount
            conn.execute("DELETE FROM pairing_tokens WHERE used_at IS NULL")
            self._audit(conn, None, "owner_reset", "ok" if changed else "not_paired")
            return bool(changed)

    def state(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM notification_state WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else None

    def set_state(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_state(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, now),
            )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        user_id: int | None,
        action: str,
        result: str,
        details: str = "",
    ) -> None:
        conn.execute(
            "INSERT INTO audit_logs(timestamp, telegram_user_id, action, result, details) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), user_id, action, result, details),
        )
