# 02 Python backend rules

Applies to `server/`, `cli/`, `routines/`, and `tests/`. Covers only the stack in
`docs/tech-stack.md`: Python 3.12+, `uv`, FastAPI + Starlette WebSockets,
`aiosqlite`, `pytest`, `ruff`. There is **no LLM library** in tether.

## Python and uv

- Target Python 3.12+. Type-hint all function signatures.
- Manage everything with `uv`: `uv add <pkg>` to add a dep, `uv run <cmd>` to run.
  Never `pip install` into the system, never hand-edit a lockfile.
- Keep modules small and single-purpose, matching the layout in `specs.md`
  section 11 (`main`, `hub`, `protocol`, `uploads`, `db`, `config`).

## FastAPI and WebSockets

- All I/O is `async`. No blocking calls inside request/WS handlers.
- WebSocket handling lives in `server/hub.py`. The hub owns the two connection
  registries (UI clients by session, routine clients by routine id) and all
  routing between them.
- Every WS frame matches the envelope and message types in `specs.md` section 5.
  Define them once in `server/protocol.py`; do not inline ad hoc frame shapes.
- tether does **no processing** of message text between receiving and dispatching.
  The routine gets the raw text, the attachments, and recent session context.
- Validate the auth token on every connect (UI and routine) once T7.1 lands.

## SQLite (aiosqlite)

- One database, schema per `specs.md` section 6. Enable **WAL** mode on open.
- Funnel all writes through a single writer (one connection or an async queue) to
  avoid `database is locked`. Reads may use their own connection.
- Plain explicit SQL. No ORM. Parameterize every query; never string-format SQL.
- A routine reply is a `messages` row (`role = 'routine'`) linked by `task_id`, so
  history and live streaming share one path.

## Uploads and media (`server/uploads.py`)

- Images and voice notes upload over HTTP (`POST /upload`), stored on disk under
  `uploads.dir`, with metadata in the `attachments` table. Enforce `uploads.max_mb`.
- Attachments expose both a `url` (browser display) and the **real host `path`**
  (so a host-native routine opens the file directly). Always include both in
  `task_available`.
- Voice transcription is a media transform only. Default is client-side Web Speech
  (no server model). Optional server-side Whisper under `voice = whisper`; it
  transcribes audio to text and never interprets. This is the only model-ish thing
  permitted, per `01-guardrails.md`.

## tether-connect (the routine bridge)

- `cli/tether_connect.py` is a thin `websockets` client exposing `next`,
  `reply`, `done`, `fail`. It speaks the protocol so the routine does not have to,
  and surfaces attachment urls + real paths to the routine.
- Keep it dependency-light and runnable as a plain CLI from a Claude `/loop`.

## Tests and quality

- Write `pytest` tests that drive the real WebSocket and upload paths (use the
  `websockets` / `httpx` test clients). Each milestone's acceptance maps to a test.
- Before committing: `uv run ruff format .`, `uv run ruff check .`,
  `uv run pytest` all clean.
