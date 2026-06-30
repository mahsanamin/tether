"""WebSocket frame envelope and message-type constants (see specs.md section 5).

tether does no processing of message text. These are just the typed frames it
moves between UI clients and routine clients.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

# UI client -> server
HELLO = "hello"
USER_MESSAGE = "user_message"
SUBSCRIBE = "subscribe"
CANCEL = "cancel"
REDISPATCH = "redispatch"
HELP_REQUEST = "help_request"
PING = "ping"

# server -> UI client
WELCOME = "welcome"
MESSAGE_APPENDED = "message_appended"
TASK_STATUS = "task_status"
SESSIONS = "sessions"
WIDGETS = "widgets"
HELP_RESULT = "help_result"
ERROR = "error"

# routine client -> server
REGISTER = "register"
CLAIM = "claim"
REPLY = "reply"
STATUS = "status"
HEARTBEAT = "heartbeat"

# server -> routine client
REGISTERED = "registered"
TASK_AVAILABLE = "task_available"
CLAIM_RESULT = "claim_result"
REVOKE = "revoke"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def frame(
    type_: str,
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build an envelope frame: {type, id, session_id, ts, payload}."""
    return {
        "type": type_,
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "ts": now_iso(),
        "payload": payload or {},
    }
