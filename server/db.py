"""SQLite data layer (WAL, single shared connection).

Schema per specs.md section 6. One connection serializes all access, so
concurrent UI + routine writes never hit `database is locked`. tether stores and
reads; it never interprets.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  task_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  message_id TEXT,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  mime TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  transcript TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  state TEXT NOT NULL,
  claimed_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'chat',
  command TEXT
);
CREATE TABLE IF NOT EXISTS routines (
  id TEXT PRIMARY KEY,
  name TEXT,
  capabilities TEXT,
  last_seen TEXT
);
CREATE TABLE IF NOT EXISTS widgets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  command TEXT NOT NULL,
  params TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


class Database:
    """One shared aiosqlite connection. Its single worker thread serializes ops."""

    def __init__(self, path: Path):
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.executescript(SCHEMA)
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        """Add columns introduced after the first schema, for existing DBs.
        CREATE TABLE IF NOT EXISTS does not alter a table that already exists."""
        # tasks.kind/command let help-probe tasks ride the queue without showing
        # in the chat (see the help_request path in the hub). widgets.params holds
        # the ask-on-click parameter spec for a widget (a JSON list).
        for table, col, ddl in (
            (
                "tasks",
                "kind",
                "ALTER TABLE tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'",
            ),
            ("tasks", "command", "ALTER TABLE tasks ADD COLUMN command TEXT"),
            ("widgets", "params", "ALTER TABLE widgets ADD COLUMN params TEXT"),
        ):
            cur = await self._db.execute(f"PRAGMA table_info({table})")
            if not any(r["name"] == col for r in await cur.fetchall()):
                await self._db.execute(ddl)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected")
        return self._db

    # ---- sessions ----
    async def create_session(self, title: str = "New chat") -> dict[str, Any]:
        sid, now = _id(), _now()
        await self.conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (sid, title, now, now),
        )
        await self.conn.commit()
        return {"id": sid, "title": title, "created_at": now, "updated_at": now}

    async def list_sessions(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
        return [dict(r) for r in await cur.fetchall()]

    async def get_or_create_default_session(self) -> dict[str, Any]:
        sessions = await self.list_sessions()
        return sessions[0] if sessions else await self.create_session("Default")

    async def touch_session(self, session_id: str) -> None:
        await self.conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id)
        )
        await self.conn.commit()

    # ---- messages ----
    async def add_message(
        self, session_id: str, role: str, content: str, task_id: str | None = None
    ) -> dict[str, Any]:
        mid, now = _id(), _now()
        await self.conn.execute(
            "INSERT INTO messages (id, session_id, role, content, task_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (mid, session_id, role, content, task_id, now),
        )
        await self.conn.commit()
        return {
            "id": mid,
            "session_id": session_id,
            "role": role,
            "content": content,
            "task_id": task_id,
            "created_at": now,
        }

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY created_at",
            (session_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_recent_messages(
        self, session_id: str, limit: int
    ) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM messages WHERE session_id=?"
            " ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        return list(reversed(rows))

    async def get_messages_after(
        self, session_id: str, after_iso: str
    ) -> list[dict[str, Any]]:
        """Incremental read for a routine following a chat by reference."""
        cur = await self.conn.execute(
            "SELECT * FROM messages WHERE session_id=? AND created_at > ?"
            " ORDER BY created_at",
            (session_id, after_iso),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def recent_context(
        self, session_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT role, content FROM messages WHERE session_id=?"
            " ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        return list(reversed(rows))

    async def get_message_text(self, message_id: str) -> str:
        cur = await self.conn.execute(
            "SELECT content FROM messages WHERE id=?", (message_id,)
        )
        row = await cur.fetchone()
        return row["content"] if row else ""

    async def update_message_content(self, message_id: str, content: str) -> None:
        await self.conn.execute(
            "UPDATE messages SET content=? WHERE id=?", (content, message_id)
        )
        await self.conn.commit()

    # ---- tasks ----
    async def create_task(self, session_id: str, message_id: str) -> dict[str, Any]:
        tid, now = _id(), _now()
        await self.conn.execute(
            "INSERT INTO tasks (id, session_id, message_id, state, claimed_by,"
            " created_at, updated_at) VALUES (?, ?, ?, 'ready', NULL, ?, ?)",
            (tid, session_id, message_id, now, now),
        )
        await self.conn.commit()
        return {
            "id": tid,
            "session_id": session_id,
            "message_id": message_id,
            "state": "ready",
        }

    async def create_help_task(self, session_id: str, command: str) -> dict[str, Any]:
        """A 'help' task carries a bare command name to probe with `<command>
        --help`. It rides the same queue (so it is replayed to a routine that
        connects later) but has no chat message; its reply is routed to the
        widget builder, not the thread. See the hub's help_request path."""
        tid, now = _id(), _now()
        await self.conn.execute(
            "INSERT INTO tasks (id, session_id, message_id, state, claimed_by,"
            " created_at, updated_at, kind, command)"
            " VALUES (?, ?, '', 'ready', NULL, ?, ?, 'help', ?)",
            (tid, session_id, now, now, command),
        )
        await self.conn.commit()
        return {
            "id": tid,
            "session_id": session_id,
            "message_id": "",
            "state": "ready",
            "kind": "help",
            "command": command,
        }

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_ready_tasks(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM tasks WHERE state='ready' ORDER BY created_at"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def claim_task(self, task_id: str, routine_id: str) -> bool:
        """Atomic claim: succeeds only if the task is still `ready`."""
        cur = await self.conn.execute(
            "UPDATE tasks SET state='claimed', claimed_by=?, updated_at=?"
            " WHERE id=? AND state='ready'",
            (routine_id, _now(), task_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def set_task_state(self, task_id: str, state: str) -> None:
        await self.conn.execute(
            "UPDATE tasks SET state=?, updated_at=? WHERE id=?",
            (state, _now(), task_id),
        )
        await self.conn.commit()

    async def rename_session(self, session_id: str, title: str) -> None:
        await self.conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (title, _now(), session_id),
        )
        await self.conn.commit()

    async def delete_session(self, session_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM attachments WHERE message_id IN"
            " (SELECT id FROM messages WHERE session_id=?)",
            (session_id,),
        )
        await self.conn.execute(
            "DELETE FROM messages WHERE session_id=?", (session_id,)
        )
        await self.conn.execute("DELETE FROM tasks WHERE session_id=?", (session_id,))
        await self.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        await self.conn.commit()

    async def maybe_set_title(self, session_id: str, text: str) -> bool:
        """Name a still-default session after its first message. No model used."""
        cur = await self.conn.execute(
            "SELECT title FROM sessions WHERE id=?", (session_id,)
        )
        row = await cur.fetchone()
        if not row or row["title"] not in ("Default", "New chat"):
            return False
        title = (text[:40] + "...") if len(text) > 40 else text
        await self.conn.execute(
            "UPDATE sessions SET title=? WHERE id=?", (title, session_id)
        )
        await self.conn.commit()
        return True

    # ---- attachments ----
    async def create_attachment(
        self,
        kind: str,
        path: str,
        mime: str,
        nbytes: int,
        transcript: str | None = None,
    ) -> dict[str, Any]:
        aid, now = _id(), _now()
        await self.conn.execute(
            "INSERT INTO attachments (id, message_id, kind, path, mime, bytes,"
            " transcript, created_at) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)",
            (aid, kind, path, mime, nbytes, transcript, now),
        )
        await self.conn.commit()
        return {"id": aid, "kind": kind, "path": path, "mime": mime, "bytes": nbytes}

    async def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM attachments WHERE id=?", (attachment_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def link_attachments(
        self, message_id: str, attachment_ids: list[str]
    ) -> None:
        for aid in attachment_ids:
            await self.conn.execute(
                "UPDATE attachments SET message_id=? WHERE id=?", (message_id, aid)
            )
        await self.conn.commit()

    async def set_transcript(self, attachment_id: str, transcript: str) -> None:
        await self.conn.execute(
            "UPDATE attachments SET transcript=? WHERE id=?",
            (transcript, attachment_id),
        )
        await self.conn.commit()

    async def message_attachments(self, message_id: str) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM attachments WHERE message_id=? ORDER BY created_at",
            (message_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    # ---- routine registry + watchdog ----
    async def stale_claimed_tasks(self, before_iso: str) -> list[dict[str, Any]]:
        # help probes are transient and have no chat message, so a stalled one
        # must not raise a "task stalled" notice in the thread.
        cur = await self.conn.execute(
            "SELECT * FROM tasks WHERE state='claimed' AND updated_at < ?"
            " AND kind != 'help'",
            (before_iso,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def upsert_routine(self, rid: str, name: str, capabilities: str) -> None:
        await self.conn.execute(
            "INSERT INTO routines (id, name, capabilities, last_seen)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
            " capabilities=excluded.capabilities, last_seen=excluded.last_seen",
            (rid, name, capabilities, _now()),
        )
        await self.conn.commit()

    async def touch_routine(self, rid: str) -> None:
        await self.conn.execute(
            "UPDATE routines SET last_seen=? WHERE id=?", (_now(), rid)
        )
        await self.conn.commit()

    async def get_inflight_tasks(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM tasks WHERE state IN"
            " ('ready', 'claimed', 'running', 'needs_attention')"
            " ORDER BY created_at DESC LIMIT 50"
        )
        return [dict(r) for r in await cur.fetchall()]

    # ---- widgets (clickable command buttons) ----
    @staticmethod
    def _widget_row(row: aiosqlite.Row) -> dict[str, Any]:
        """A widget row, with its stored params JSON parsed back into a list.
        `command` may be a template with {{key}} placeholders that the client
        fills from `params` (a list of {key, label, default}) at click time."""
        d = dict(row)
        try:
            d["params"] = json.loads(d.get("params") or "[]")
        except (ValueError, TypeError):
            d["params"] = []
        return d

    async def create_widget(
        self, name: str, command: str, params: list | None = None
    ) -> dict[str, Any]:
        wid, now = _id(), _now()
        await self.conn.execute(
            "INSERT INTO widgets (id, name, command, params, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (wid, name, command, json.dumps(params or []), now),
        )
        await self.conn.commit()
        return {
            "id": wid,
            "name": name,
            "command": command,
            "params": params or [],
            "created_at": now,
        }

    async def list_widgets(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute("SELECT * FROM widgets ORDER BY created_at")
        return [self._widget_row(r) for r in await cur.fetchall()]

    async def update_widget(
        self, widget_id: str, name: str, command: str, params: list | None = None
    ) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "UPDATE widgets SET name=?, command=?, params=? WHERE id=?",
            (name, command, json.dumps(params or []), widget_id),
        )
        await self.conn.commit()
        if cur.rowcount == 0:
            return None
        row = await (
            await self.conn.execute("SELECT * FROM widgets WHERE id=?", (widget_id,))
        ).fetchone()
        return self._widget_row(row) if row else None

    async def delete_widget(self, widget_id: str) -> None:
        await self.conn.execute("DELETE FROM widgets WHERE id=?", (widget_id,))
        await self.conn.commit()
