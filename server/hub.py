"""WebSocket hub: routes messages between UI clients and routine clients.

tether does no processing of message text. It persists the message, fans it out
to the UI clients watching the session, and dispatches the raw text + recent
context to routines. Replies flow back the same way. See specs.md sections 4-5.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import WebSocket

from server import protocol as P
from server.db import Database

# A command the widget builder may probe with `<command> --help`. Restricted to a
# bare name or path so the probe is exactly that and cannot smuggle shell syntax
# (no spaces, pipes, quotes, etc.). tether never runs it; the routine does.
_COMMAND_RE = re.compile(r"^[A-Za-z0-9_./][\w./-]*$")


class Hub:
    def __init__(self, db: Database):
        self.db = db
        self.ui: dict[WebSocket, str] = {}  # UI socket -> session it watches
        self.routines: dict[str, WebSocket] = {}  # routine_id -> socket
        self.routine_ids: dict[WebSocket, str] = {}  # socket -> routine_id
        self.caps: dict[str, list] = {}  # routine_id -> capabilities
        self.claim_timeout = int(os.environ.get("TETHER_CLAIM_TIMEOUT", "300"))
        self.auth_token = ""  # set by main; default/empty means open access
        self.voice_provider = "browser"  # set by main from config

    # ---- send helpers ----
    async def _send(self, ws: WebSocket, frame: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(frame))
        except Exception:
            pass

    async def _broadcast_session(self, session_id: str, frame: dict[str, Any]) -> None:
        for ws, sid in list(self.ui.items()):
            if sid == session_id:
                await self._send(ws, frame)

    async def broadcast_sessions(self) -> None:
        """Push the current session list to every UI client (after a change)."""
        sessions = await self.db.list_sessions()
        f = P.frame(P.SESSIONS, {"sessions": sessions})
        for ws in list(self.ui.keys()):
            await self._send(ws, f)

    async def append_routine_reply(
        self, session_id: str, content: str, task_id: str | None = None
    ) -> dict[str, Any]:
        """Append a routine reply and fan it out. Used by the REST reply path so a
        routine can answer a chat by its reference without holding a socket."""
        msg = await self.db.add_message(session_id, "routine", content, task_id=task_id)
        await self.db.touch_session(session_id)
        await self._broadcast_session(
            session_id,
            P.frame(
                P.MESSAGE_APPENDED,
                {
                    "message_id": msg["id"],
                    "role": "routine",
                    "content": content,
                    "attachments": [],
                    "ts": msg["created_at"],
                },
                session_id,
            ),
        )
        return msg

    async def _attachments_payload(self, message_id: str) -> list[dict[str, Any]]:
        atts = await self.db.message_attachments(message_id)
        return [
            {
                "id": a["id"],
                "kind": a["kind"],
                "mime": a["mime"],
                "url": f"/attachment/{a['id']}",
                "path": a["path"],
                "transcript": a["transcript"],
            }
            for a in atts
        ]

    async def _handle_audio_transcripts(self, message_id: str, text: str) -> None:
        from server import uploads

        for a in await self.db.message_attachments(message_id):
            if a["kind"] == "audio" and not a["transcript"]:
                transcript = text or await asyncio.to_thread(
                    uploads.transcribe_audio, a["path"]
                )
                if transcript:
                    await self.db.set_transcript(a["id"], transcript)

    async def _audio_transcript(self, message_id: str) -> str:
        atts = await self.db.message_attachments(message_id)
        return " ".join(
            a["transcript"] for a in atts if a["kind"] == "audio" and a["transcript"]
        ).strip()

    async def _task_available_frame(self, task: dict[str, Any]) -> dict[str, Any]:
        if task.get("kind") == "help":
            # Probe the command's own --help. No message, attachments, or context:
            # the routine just runs it and replies with the help text.
            return P.frame(
                P.TASK_AVAILABLE,
                {
                    "task_id": task["id"],
                    "session_id": task["session_id"],
                    "text": f"{task['command']} --help",
                    "attachments": [],
                    "context": [],
                },
                session_id=task["session_id"],
            )
        text = await self.db.get_message_text(task["message_id"])
        context = await self.db.recent_context(task["session_id"])
        attachments = await self._attachments_payload(task["message_id"])
        return P.frame(
            P.TASK_AVAILABLE,
            {
                "task_id": task["id"],
                "session_id": task["session_id"],
                "text": text,
                "attachments": attachments,
                "context": context,
            },
            session_id=task["session_id"],
        )

    async def _system(
        self, session_id: str, text: str, task_id: str | None = None
    ) -> None:
        msg = await self.db.add_message(session_id, "system", text, task_id=task_id)
        await self._broadcast_session(
            session_id,
            P.frame(
                P.MESSAGE_APPENDED,
                {
                    "message_id": msg["id"],
                    "role": "system",
                    "content": text,
                    "attachments": [],
                    "ts": msg["created_at"],
                },
                session_id,
            ),
        )

    # ---- UI side ----
    def _auth_required(self) -> bool:
        return self.auth_token not in ("", "change-me")

    async def ui_connect(self, ws: WebSocket) -> None:
        await ws.accept()
        if not self._auth_required():
            await self._admit_ui(ws)

    async def _admit_ui(self, ws: WebSocket) -> None:
        session = await self.db.get_or_create_default_session()
        self.ui[ws] = session["id"]
        sessions = await self.db.list_sessions()
        widgets = await self.db.list_widgets()
        await self._send(
            ws,
            P.frame(
                P.WELCOME,
                {
                    "session_id": session["id"],
                    "sessions": sessions,
                    "voice": self.voice_provider,
                    "widgets": widgets,
                },
                session["id"],
            ),
        )

    async def broadcast_widgets(self) -> None:
        """Push the widget list to every UI client (after a change)."""
        widgets = await self.db.list_widgets()
        f = P.frame(P.WIDGETS, {"widgets": widgets})
        for ws in list(self.ui.keys()):
            await self._send(ws, f)

    async def ui_message(self, ws: WebSocket, data: dict[str, Any]) -> None:
        type_ = data.get("type")
        payload = data.get("payload", {})
        if type_ == P.HELLO:
            if self._auth_required() and ws not in self.ui:
                if payload.get("token") == self.auth_token:
                    await self._admit_ui(ws)
                else:
                    await self._send(
                        ws,
                        P.frame(
                            P.ERROR,
                            {"code": "unauthorized", "message": "invalid token"},
                        ),
                    )
                    await ws.close()
            return
        if self._auth_required() and ws not in self.ui:
            return  # ignore everything until admitted
        if type_ == P.SUBSCRIBE:
            sid = payload.get("session_id")
            if sid:
                self.ui[ws] = sid
            return
        if type_ == P.PING:
            return
        if type_ == P.CANCEL:
            await self._cancel_task(payload.get("task_id"))
            return
        if type_ == P.REDISPATCH:
            await self._redispatch_task(payload.get("task_id"))
            return
        if type_ == P.HELP_REQUEST:
            await self._help_request(ws, payload.get("command"))
            return
        if type_ == P.USER_MESSAGE:
            session_id = self.ui.get(ws)
            text = (payload.get("text") or "").strip()
            attachment_ids = payload.get("attachment_ids") or []
            if not session_id or (not text and not attachment_ids):
                return
            msg = await self.db.add_message(session_id, "user", text)
            if attachment_ids:
                await self.db.link_attachments(msg["id"], attachment_ids)
                await self._handle_audio_transcripts(msg["id"], text)
                if not text:
                    spoken = await self._audio_transcript(msg["id"])
                    if spoken:
                        text = spoken
                        await self.db.update_message_content(msg["id"], spoken)
            await self.db.touch_session(session_id)
            attachments = await self._attachments_payload(msg["id"])
            task = await self.db.create_task(session_id, msg["id"])
            await self._broadcast_session(
                session_id,
                P.frame(
                    P.MESSAGE_APPENDED,
                    {
                        "message_id": msg["id"],
                        "role": "user",
                        "content": text,
                        "attachments": attachments,
                        "task_id": task["id"],
                        "ts": msg["created_at"],
                    },
                    session_id,
                ),
            )
            ta = await self._task_available_frame(task)
            for rws in list(self.routines.values()):
                await self._send(rws, ta)
            await self._broadcast_session(
                session_id,
                P.frame(
                    P.TASK_STATUS, {"task_id": task["id"], "state": "ready"}, session_id
                ),
            )
            if await self.db.maybe_set_title(session_id, text or "(media)"):
                await self.broadcast_sessions()

    async def ui_disconnect(self, ws: WebSocket) -> None:
        self.ui.pop(ws, None)

    # ---- routine side ----
    async def routine_connect(self, ws: WebSocket) -> None:
        await ws.accept()

    async def routine_message(self, ws: WebSocket, data: dict[str, Any]) -> None:
        type_ = data.get("type")
        payload = data.get("payload", {})

        if self._auth_required() and payload.get("token") != self.auth_token:
            await self._send(ws, P.frame(P.ERROR, {"code": "unauthorized"}))
            await ws.close()
            return

        if type_ == P.REGISTER:
            rid = payload.get("routine_id") or "routine"
            name = payload.get("name") or rid
            caps = payload.get("capabilities") or []
            self.routines[rid] = ws
            self.routine_ids[ws] = rid
            self.caps[rid] = caps
            # Send registered FIRST, before any awaiting db call, so a concurrent
            # user_message dispatch cannot slip a task_available ahead of it.
            await self._send(
                ws, P.frame(P.REGISTERED, {"ok": True, "since": P.now_iso()})
            )
            for task in await self.db.get_ready_tasks():  # replay (gap B)
                await self._send(ws, await self._task_available_frame(task))
            await self.db.upsert_routine(rid, name, json.dumps(caps))
            return

        if type_ == P.CLAIM:
            tid = payload.get("task_id")
            rid = self.routine_ids.get(ws, "routine")
            granted = await self.db.claim_task(tid, rid)
            await self._send(
                ws, P.frame(P.CLAIM_RESULT, {"task_id": tid, "granted": granted})
            )
            if granted:
                task = await self.db.get_task(tid)
                if task and task.get("kind") != "help":
                    await self._broadcast_session(
                        task["session_id"],
                        P.frame(
                            P.TASK_STATUS,
                            {"task_id": tid, "state": "claimed", "claimed_by": rid},
                            task["session_id"],
                        ),
                    )
            return

        if type_ == P.REPLY:
            tid = payload.get("task_id")
            content = payload.get("content", "")
            task = await self.db.get_task(tid)
            if not task:
                return
            sid = task["session_id"]
            if task.get("kind") == "help":
                # Relay the raw --help text to the builder; never into the chat.
                # The client strips fences and parses it into form fields.
                await self.db.set_task_state(tid, "running")
                await self._broadcast_session(
                    sid,
                    P.frame(
                        P.HELP_RESULT,
                        {"command": task.get("command"), "ok": True, "text": content},
                        sid,
                    ),
                )
                return
            await self.db.set_task_state(tid, "running")
            msg = await self.db.add_message(sid, "routine", content, task_id=tid)
            await self.db.touch_session(sid)
            await self._broadcast_session(
                sid,
                P.frame(
                    P.MESSAGE_APPENDED,
                    {
                        "message_id": msg["id"],
                        "role": "routine",
                        "content": content,
                        "attachments": [],
                        "ts": msg["created_at"],
                    },
                    sid,
                ),
            )
            return

        if type_ == P.STATUS:
            tid = payload.get("task_id")
            state = payload.get("state", "completed")
            task = await self.db.get_task(tid)
            if not task:
                return
            sid = task["session_id"]
            await self.db.set_task_state(tid, state)
            if task.get("kind") == "help":
                return  # help probes never surface in the chat
            if state == "failed":  # surface failures in chat (gap C)
                await self._system(
                    sid,
                    f"Routine task failed: {payload.get('reason', 'unknown error')}",
                    tid,
                )
            await self._broadcast_session(
                sid, P.frame(P.TASK_STATUS, {"task_id": tid, "state": state}, sid)
            )
            return

        if type_ == P.HEARTBEAT:
            rid = self.routine_ids.get(ws)
            if rid:
                await self.db.touch_routine(rid)
            return

    async def routine_disconnect(self, ws: WebSocket) -> None:
        # Deregister. Stalled in-flight tasks are caught by the watchdog (T5.3/E),
        # which fits the connector model where routines connect only briefly.
        rid = self.routine_ids.pop(ws, None)
        if rid:
            self.routines.pop(rid, None)
            self.caps.pop(rid, None)

    async def _cancel_task(self, task_id: str | None) -> None:
        if not task_id:
            return
        task = await self.db.get_task(task_id)
        if not task or task["state"] not in ("ready", "claimed", "running"):
            return
        await self.db.set_task_state(task_id, "needs_attention")
        rid = task.get("claimed_by")
        if rid and rid in self.routines:
            await self._send(
                self.routines[rid],
                P.frame(P.REVOKE, {"task_id": task_id, "reason": "cancelled"}),
            )
        await self._system(task["session_id"], "Task cancelled.", task_id)
        await self._broadcast_session(
            task["session_id"],
            P.frame(
                P.TASK_STATUS,
                {"task_id": task_id, "state": "needs_attention"},
                task["session_id"],
            ),
        )

    async def _redispatch_task(self, task_id: str | None) -> None:
        if not task_id:
            return
        task = await self.db.get_task(task_id)
        if not task or task["state"] != "needs_attention":
            return
        await self.db.set_task_state(task_id, "ready")
        fresh = await self.db.get_task(task_id)
        ta = await self._task_available_frame(fresh)
        for rws in list(self.routines.values()):
            await self._send(rws, ta)
        await self._broadcast_session(
            task["session_id"],
            P.frame(
                P.TASK_STATUS,
                {"task_id": task_id, "state": "ready"},
                task["session_id"],
            ),
        )

    async def _help_request(self, ws: WebSocket, command: Any) -> None:
        """Queue a help probe for `command` so a routine runs `command --help`.
        tether never runs it; it only validates the name is a bare command (no
        shell syntax) and relays the routine's reply back to the builder."""
        session_id = self.ui.get(ws)
        command = (command or "").strip() if isinstance(command, str) else ""
        if not session_id or not _COMMAND_RE.match(command):
            await self._send(
                ws,
                P.frame(
                    P.HELP_RESULT,
                    {"command": command, "ok": False, "error": "invalid command"},
                ),
            )
            return
        if not self.routines:
            await self._send(
                ws,
                P.frame(
                    P.HELP_RESULT,
                    {"command": command, "ok": False, "error": "no routine connected"},
                ),
            )
            return
        task = await self.db.create_help_task(session_id, command)
        ta = await self._task_available_frame(task)
        for rws in list(self.routines.values()):
            await self._send(rws, ta)

    async def watchdog(self) -> None:
        """Flag tasks claimed but never progressed (likely a crashed routine)."""
        while True:
            try:
                await asyncio.sleep(15)
                cutoff = (
                    datetime.now(UTC) - timedelta(seconds=self.claim_timeout)
                ).isoformat()
                for task in await self.db.stale_claimed_tasks(cutoff):
                    await self.db.set_task_state(task["id"], "needs_attention")
                    await self._system(
                        task["session_id"],
                        "A claimed task stalled and needs attention.",
                        task["id"],
                    )
                    await self._broadcast_session(
                        task["session_id"],
                        P.frame(
                            P.TASK_STATUS,
                            {"task_id": task["id"], "state": "needs_attention"},
                            task["session_id"],
                        ),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    async def get_status(self) -> dict[str, Any]:
        return {
            "connected_routines": [
                {"id": rid, "capabilities": self.caps.get(rid, [])}
                for rid in self.routines
            ],
            "ui_clients": len(self.ui),
            "tasks": await self.db.get_inflight_tasks(),
        }
