"""SQLite memory: users, per-user turn history (short-term audit), long-term profile, and the LangGraph checkpointer's tables, all in ONE file.

Hard caps (config [settings.memory]): max_users users and max_turns turns per user. A new user beyond the cap evicts the oldest user
(smallest created_at) together with their turns, profile and checkpoints; a turn beyond the cap drops that user's oldest turn.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from config import BACKEND, settings

_M = settings.memory
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY, created_at REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, ts REAL NOT NULL,
    question TEXT, answer TEXT, status TEXT, format TEXT, clause TEXT, digest TEXT);
CREATE INDEX IF NOT EXISTS turns_user ON turns(user_id, id);
CREATE TABLE IF NOT EXISTS user_memory (
    user_id TEXT PRIMARY KEY, preferred_format TEXT, preferred_language TEXT, topics TEXT NOT NULL DEFAULT '[]', updated_at REAL NOT NULL);
"""


def default_db_path() -> Path:
    """Database file: $CREASEIQ_MEMORY_DB, else settings.memory.db_path (relative paths resolve against the project root)."""
    raw = Path(os.environ.get("CREASEIQ_MEMORY_DB") or _M.db_path)
    return raw if raw.is_absolute() else BACKEND.parent / raw


class MemoryStore:
    """Owns the SQLite connection (shared with the LangGraph SqliteSaver) and enforces the user and turn caps."""

    def __init__(self, path: str | Path | None = None, max_users: int | None = None, max_turns: int | None = None, max_topics: int | None = None):
        """Open (creating if needed) the database in WAL mode and create the tables."""
        self.path = Path(path) if path else default_db_path()
        self.max_users, self.max_turns, self.max_topics = max_users or _M.max_users, max_turns or _M.max_turns, max_topics or _M.max_topics
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)      # autocommit; explicit BEGIN where needed
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        if "digest" not in [r[1] for r in self.conn.execute("PRAGMA table_info(turns)")]:      # database created before digests existed
            self.conn.execute("ALTER TABLE turns ADD COLUMN digest TEXT")
        self.lock = threading.RLock()

    # ---- users -----------------------------------------------------------------------------------------------
    def ensure_user(self, user_id: str) -> list[str]:
        """Register or touch a user. A new user over the cap evicts the oldest user(s); returns the evicted user ids."""
        evicted: list[str] = []
        with self.lock:
            now = time.time()
            if self.conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
                self.conn.execute("UPDATE users SET last_seen=? WHERE user_id=?", (now, user_id))
                return evicted
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                while self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= self.max_users:
                    oldest = self.conn.execute("SELECT user_id FROM users ORDER BY created_at, rowid LIMIT 1").fetchone()[0]
                    self._delete_user(oldest)
                    evicted.append(oldest)
                self.conn.execute("INSERT INTO users(user_id, created_at, last_seen) VALUES (?,?,?)", (user_id, now, now))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return evicted

    def _delete_user(self, user_id: str) -> None:
        """Remove everything stored for a user (call inside a transaction)."""
        for table in ("users", "turns", "user_memory", "checkpoints", "writes"):
            if table in ("checkpoints", "writes") and not self._has_table(table):
                continue
            self.conn.execute(f"DELETE FROM {table} WHERE {'thread_id' if table in ('checkpoints', 'writes') else 'user_id'}=?", (user_id,))

    def _has_table(self, name: str) -> bool:
        """True when the table exists (the checkpointer creates its own tables on setup)."""
        return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def delete_user(self, user_id: str) -> None:
        """Forget a user completely (e.g. on a deletion request)."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            self._delete_user(user_id)
            self.conn.execute("COMMIT")

    # ---- turns (short-term history) -------------------------------------------------------------------------------
    def record_turn(self, user_id: str, question: str, answer: str, status: str, fmt: Optional[str], clause: Optional[str], digest: Optional[dict] = None) -> None:
        """Append a turn and drop the user's oldest turns beyond max_turns."""
        with self.lock:
            self.conn.execute("INSERT INTO turns(user_id, ts, question, answer, status, format, clause, digest) VALUES (?,?,?,?,?,?,?,?)",
                              (user_id, time.time(), question, answer, status, fmt, clause, json.dumps(digest) if digest else None))
            self.conn.execute("DELETE FROM turns WHERE user_id=? AND id NOT IN (SELECT id FROM turns WHERE user_id=? ORDER BY id DESC LIMIT ?)",
                              (user_id, user_id, self.max_turns))

    def turns(self, user_id: str) -> list[dict]:
        """The user's stored turns, oldest first."""
        cur = self.conn.execute("SELECT ts, question, answer, status, format, clause, digest FROM turns WHERE user_id=? ORDER BY id", (user_id,))
        rows = [dict(zip(("ts", "question", "answer", "status", "format", "clause", "digest"), r)) for r in cur.fetchall()]
        for r in rows:
            r["digest"] = json.loads(r["digest"]) if r["digest"] else None
        return rows

    # ---- long-term profile ----------------------------------------------------------------------------------------
    def get_profile(self, user_id: str) -> dict:
        """The user's long-term memory: preferred_format, preferred_language, topics (empty values when nothing is stored)."""
        row = self.conn.execute("SELECT preferred_format, preferred_language, topics FROM user_memory WHERE user_id=?", (user_id,)).fetchone()
        return {"preferred_format": row[0], "preferred_language": row[1], "topics": json.loads(row[2])} if row else \
               {"preferred_format": None, "preferred_language": None, "topics": []}

    def update_profile(self, user_id: str, fmt: Optional[str] = None, language: Optional[str] = None, topic: Optional[str] = None) -> None:
        """Remember the latest resolved format and language, and add a topic (most recent last, deduplicated, capped at max_topics)."""
        with self.lock:
            p = self.get_profile(user_id)
            topics = [t for t in p["topics"] if t != topic] + ([topic] if topic else [])
            self.conn.execute("INSERT INTO user_memory(user_id, preferred_format, preferred_language, topics, updated_at) VALUES (?,?,?,?,?) "
                              "ON CONFLICT(user_id) DO UPDATE SET preferred_format=excluded.preferred_format, preferred_language=excluded.preferred_language, "
                              "topics=excluded.topics, updated_at=excluded.updated_at",
                              (user_id, fmt or p["preferred_format"], language or p["preferred_language"], json.dumps(topics[-self.max_topics:]), time.time()))

    # ---- checkpoints ----------------------------------------------------------------------------------------------
    def prune_checkpoints(self, user_id: str) -> None:
        """Keep only the newest checkpoint of the user's thread (the graph writes ~20 per turn); the latest state is all that is ever resumed."""
        if not self._has_table("checkpoints"):
            return
        with self.lock:
            for table in ("checkpoints", "writes"):
                self.conn.execute(f"DELETE FROM {table} WHERE thread_id=? AND checkpoint_id < (SELECT MAX(checkpoint_id) FROM checkpoints WHERE thread_id=?)",
                                  (user_id, user_id))


_STORE: Optional[MemoryStore] = None


def get_store() -> MemoryStore:
    """The process-wide store (created on first use from the config)."""
    global _STORE
    if _STORE is None:
        _STORE = MemoryStore()
    return _STORE
