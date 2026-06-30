"""tether FastAPI app: a private bridge between you and your Claude routines.

Serves the chat UI and a WebSocket hub. tether runs no LLM: it persists and
streams messages, and hands routines the raw message + context. See CLAUDE.md
and docs/ai-rules/01-guardrails.md.
"""

import asyncio
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import config as config_mod
from server import uploads
from server.db import Database
from server.hub import Hub

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DB_PATH = Path(os.environ.get("TETHER_DB") or (ROOT / "tether.db"))

# M0 defaults, overridable by env until the config loader lands in T6.1.
# Default stays on loopback (safe pre-auth). A Dockerized reverse proxy reaches
# it via host.docker.internal on Docker Desktop for Mac. See specs.md section 8.
CFG = config_mod.load(ROOT)
HOST = CFG["server"]["bind"]
PORT = CFG["server"]["port"]
AUTH_TOKEN = CFG["server"]["auth_token"]
_upload = Path(CFG["uploads"]["dir"])
UPLOAD_DIR = _upload if _upload.is_absolute() else (ROOT / _upload)
MAX_BYTES = CFG["uploads"]["max_mb"] * 1024 * 1024

db = Database(DB_PATH)
hub = Hub(db)
hub.auth_token = AUTH_TOKEN
hub.voice_provider = CFG["voice"]["provider"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    for warning in config_mod.validate(CFG, UPLOAD_DIR):
        print(f"[tether] WARNING: {warning}")
    await db.connect()
    watchdog = asyncio.create_task(hub.watchdog())
    try:
        yield
    finally:
        watchdog.cancel()
        await db.close()


app = FastAPI(title="tether", lifespan=lifespan)


@app.middleware("http")
async def no_cache_assets(request: Request, call_next):
    """Make the UI shell revalidate every load. Browsers heuristically cache
    .css/.js without a Cache-Control header, which served a stale stylesheet; this
    forces a conditional check (ETag -> 304 when unchanged, fresh when changed) so
    a deploy is always picked up. The assets are tiny and local, so the cost is
    negligible."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(
        (".html", ".js", ".css", ".svg", ".webmanifest", ".ico", ".png")
    ):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def _rest_authed(request: Request) -> bool:
    """REST auth gate for sensitive endpoints (open unless a real token is set)."""
    if not config_mod.auth_required(AUTH_TOKEN):
        return True
    return request.headers.get("x-tether-token") == AUTH_TOKEN


def _clean_params(raw) -> list:
    """Sanitize a widget's ask-on-click param spec. Each entry is a plain
    {key, label, default} of strings; the key matches a {{key}} placeholder in
    the command. tether only stores this; the client fills and substitutes it."""
    out = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if not re.fullmatch(r"\w+", key) or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "key": key,
                "label": str(item.get("label", key))[:80],
                "default": str(item.get("default", ""))[:2000],
            }
        )
    return out


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/widgets")
async def list_widgets(request: Request):
    if not _rest_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    return await db.list_widgets()


@app.post("/api/widgets")
async def create_widget(request: Request, body: dict):
    if not _rest_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    name = (body or {}).get("name", "").strip()
    command = (body or {}).get("command", "").strip()
    if not name or not command:
        return JSONResponse({"error": "name and command required"}, status_code=400)
    widget = await db.create_widget(
        name, command, _clean_params((body or {}).get("params"))
    )
    await hub.broadcast_widgets()
    return widget


@app.put("/api/widgets/{widget_id}")
async def update_widget(request: Request, widget_id: str, body: dict):
    if not _rest_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    name = (body or {}).get("name", "").strip()
    command = (body or {}).get("command", "").strip()
    if not name or not command:
        return JSONResponse({"error": "name and command required"}, status_code=400)
    widget = await db.update_widget(
        widget_id, name, command, _clean_params((body or {}).get("params"))
    )
    if widget is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    await hub.broadcast_widgets()
    return widget


@app.delete("/api/widgets/{widget_id}")
async def delete_widget(request: Request, widget_id: str):
    if not _rest_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    await db.delete_widget(widget_id)
    await hub.broadcast_widgets()
    return {"ok": True}


@app.get("/api/status")
async def status() -> dict:
    return await hub.get_status()


@app.get("/api/dirs")
async def list_dirs(request: Request, path: str | None = Query(default=None)):
    """List subdirectories of a host path so the UI can pick a folder. Returns
    directory names only (no file contents, no file reads). Gated by the auth
    token when auth is enabled."""
    if config_mod.auth_required(AUTH_TOKEN):
        if request.headers.get("x-tether-token") != AUTH_TOKEN:
            return JSONResponse({"error": "unauthorized"}, status_code=403)
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except Exception:
        return JSONResponse({"error": "bad path"}, status_code=400)
    if not base.is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    dirs: list[str] = []
    try:
        # non-hidden folders first, then dotfolders; each alphabetical
        ordered = sorted(
            base.iterdir(), key=lambda p: (p.name.startswith("."), p.name.lower())
        )
        for entry in ordered:
            try:
                if entry.is_dir():
                    dirs.append(entry.name)
            except OSError:
                continue
            if len(dirs) >= 1000:
                break
    except PermissionError:
        return JSONResponse(
            {"error": "permission denied", "path": str(base)}, status_code=403
        )
    parent = str(base.parent) if base.parent != base else None
    return {"path": str(base), "parent": parent, "dirs": dirs}


_cmd_cache: dict = {"ts": 0.0, "cmds": []}


def _scan_path_commands() -> list[str]:
    found: set[str] = set()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        try:
            for name in os.listdir(d):
                full = os.path.join(d, name)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    found.add(name)
        except OSError:
            continue
    return sorted(found)


@app.get("/api/commands")
async def list_commands(request: Request, q: str | None = Query(default=None)):
    """List executable command names on the host PATH so the UI can pick one.
    Cached for 60s. Token-gated when auth is enabled."""
    if config_mod.auth_required(AUTH_TOKEN):
        if request.headers.get("x-tether-token") != AUTH_TOKEN:
            return JSONResponse({"error": "unauthorized"}, status_code=403)
    now = time.monotonic()
    if not _cmd_cache["cmds"] or now - _cmd_cache["ts"] > 60:
        _cmd_cache["cmds"] = await asyncio.to_thread(_scan_path_commands)
        _cmd_cache["ts"] = now
    cmds = _cmd_cache["cmds"]
    if q:
        ql = q.lower()
        cmds = [c for c in cmds if c.lower().startswith(ql)]
    return {"commands": cmds[:5000]}


@app.get("/api/sessions")
async def list_sessions() -> list[dict]:
    return await db.list_sessions()


@app.post("/api/sessions")
async def create_session(body: dict | None = None) -> dict:
    session = await db.create_session((body or {}).get("title", "New chat"))
    await hub.broadcast_sessions()
    return session


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, body: dict) -> dict:
    await db.rename_session(session_id, (body or {}).get("title", "New chat"))
    await hub.broadcast_sessions()
    return {"ok": True}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    await db.delete_session(session_id)
    await hub.broadcast_sessions()
    return {"ok": True}


async def _enrich(msgs: list[dict]) -> list[dict]:
    for m in msgs:
        atts = await db.message_attachments(m["id"])
        m["attachments"] = [
            {
                "id": a["id"],
                "kind": a["kind"],
                "mime": a["mime"],
                "url": f"/attachment/{a['id']}",
                "transcript": a["transcript"],
            }
            for a in atts
        ]
    return msgs


@app.get("/api/sessions/{session_id}/messages")
async def session_messages(
    session_id: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=0),
) -> list[dict]:
    """Full history, the last `limit` messages, or messages after an ISO
    timestamp (incremental read for a routine following a chat by reference)."""
    if after:
        msgs = await db.get_messages_after(session_id, after)
    elif limit and limit > 0:
        msgs = await db.get_recent_messages(session_id, limit)
    else:
        msgs = await db.get_messages(session_id)
    return await _enrich(msgs)


@app.post("/api/sessions/{session_id}/reply")
async def post_reply(session_id: str, body: dict) -> dict:
    """A routine replies into a chat by its reference (no socket needed)."""
    msg = await hub.append_routine_reply(session_id, (body or {}).get("content", ""))
    return {"ok": True, "message_id": msg["id"]}


@app.post("/upload")
async def upload(file: UploadFile = File(...), kind: str = Form(default="file")):
    data = await file.read()
    if len(data) > MAX_BYTES:
        return JSONResponse({"error": "file too large"}, status_code=413)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "").suffix
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    dest.write_bytes(data)
    # Never trust the client MIME or kind: normalize to a safe-to-inline type or
    # a download, and derive the kind from that.
    mime = uploads.safe_mime(file.content_type or "")
    realkind = uploads.guess_kind(mime)
    att = await db.create_attachment(realkind, str(dest), mime, len(data))
    return {
        "attachment_id": att["id"],
        "kind": realkind,
        "mime": mime,
        "bytes": len(data),
    }


@app.get("/attachment/{attachment_id}")
async def get_attachment(attachment_id: str):
    att = await db.get_attachment(attachment_id)
    if not att:
        return JSONResponse({"error": "not found"}, status_code=404)
    headers = {
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    if att["mime"] in uploads.INLINE_MIMES:
        return FileResponse(att["path"], media_type=att["mime"], headers=headers)
    # Unknown/unsafe type: force a download so the browser never renders it inline.
    headers["Content-Disposition"] = "attachment"
    return FileResponse(
        att["path"], media_type="application/octet-stream", headers=headers
    )


@app.websocket("/ws/ui")
async def ws_ui(ws: WebSocket) -> None:
    await hub.ui_connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            await hub.ui_message(ws, data)
    except WebSocketDisconnect:
        await hub.ui_disconnect(ws)
    except Exception:
        await hub.ui_disconnect(ws)


@app.websocket("/ws/routine")
async def ws_routine(ws: WebSocket) -> None:
    await hub.routine_connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            await hub.routine_message(ws, data)
    except WebSocketDisconnect:
        await hub.routine_disconnect(ws)
    except Exception:
        await hub.routine_disconnect(ws)


# The static UI shell is mounted last so explicit routes win.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def run() -> None:
    """Entry point for `uv run tether`."""
    import uvicorn

    uvicorn.run("server.main:app", host=HOST, port=PORT)
