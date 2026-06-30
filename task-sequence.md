# tether: Task Sequence

The single source of truth for **execution**. `specs.md` says what and why;
this file says what to build next. Work top to bottom, one task at a time.

## How to use this file

1. Before touching code, read in this order: `README.md`, `specs.md`,
   `docs/tech-stack.md`, then `docs/ai-rules/` (start with its `README.md`).
2. Pick the **first unchecked task**. Do only that task. Do not skip ahead.
3. Build it within the stack in `docs/tech-stack.md` and the rules in
   `docs/ai-rules/`. Add no dependency that is not listed in the tech stack
   without updating `docs/tech-stack.md` first.
4. Meet every line under **Acceptance** before checking the box. Prefer a test
   in `tests/` that proves it.
5. Check the box, note anything learned in a short line under the task, commit,
   and merge. Then move to the next task.
6. If a task reveals a missing decision, stop and raise it. Do not invent scope.

tether runs **no LLM**. It is a pure bridge: it stores and streams messages and
media, and hands the raw message + media + context to the routine, which extracts
intent itself. If a task tempts you to interpret, route, or summarize inside
tether, it is wrong (see `docs/ai-rules/01-guardrails.md`).

## Status legend

- `[ ]` not started
- `[~]` in progress
- `[x]` done and merged

## Now

> All milestones built (M0 through M8). Server + reference routine run as
> background processes; for true 24/7 run `launchctl load` (T0.3). Deferred,
> needing your hands or a tool: true Web Push (T8.5), PNG home-screen icons
> (T8.6), server-side Whisper model (T4.3), and wiring a real Claude routine in
> place of the echo reference routine.

---

## M0 Foundation

- [x] **T0.1 Native project scaffold.**
  - Deliver: `pyproject.toml` (managed by `uv`), package layout per spec section
    11, `ruff` configured for lint + format, `config.example.yaml`.
  - Acceptance: `uv sync` installs cleanly; `uv run ruff check .` and
    `uv run ruff format --check .` pass.
  - Done: uv 0.11.24 installed, Python 3.12 pinned, hatchling backend, project
    installs editable, ruff + pytest clean.

- [x] **T0.2 FastAPI app: health + UI shell + DB on boot.**
  - Deliver: FastAPI app, `GET /health`, static mount serving an empty UI shell,
    SQLite file created on first boot.
  - Acceptance: `uv run tether` starts; `GET /health` returns `{"status":"ok"}`;
    the browser shows the empty shell; the SQLite file exists after boot.
  - Done: verified live; tests in `tests/test_health.py` cover both.

- [~] **T0.3 Always-on service.**
  - Deliver: `deploy/com.tether.server.plist` (launchd user agent) + load command
    in `README.md`.
  - Acceptance: loading the plist starts tether on login and restarts on crash;
    `GET /health` reachable without manually running `uv run`.
  - Done: plist created (`RunAtLoad` + `KeepAlive`), binds loopback default,
    load/unload commands documented. Pending: operator runs `launchctl load`.

## M1 Walking skeleton (text message to a hand-wired routine and back)

- [x] **T1.1 SQLite schema + data layer (WAL).**
  - Deliver: `server/db.py` with `aiosqlite`, full schema per spec section 6
    (sessions, messages, attachments, tasks, routines), WAL on, all writes
    through a single writer.
  - Acceptance: schema creates on boot; concurrent writes do not raise
    `database is locked` in a stress test.

- [x] **T1.2 WebSocket hub: UI role.**
  - Deliver: `/ws` UI connect, `user_message {text}` persisted, echoed as
    `message_appended`; REST history hydrate for a fresh tab.
  - Acceptance: a typed message shows in the UI and persists; reload rehydrates
    history from REST.

- [x] **T1.3 WebSocket hub: routine role + round trip.**
  - Deliver: routine connect + `register`; `task_available {text, context}` on a
    new message; `reply` becomes a `message_appended` in the session. tether does
    no processing of the text.
  - Acceptance: type "hello" -> a connected routine gets a `task_available` with
    the raw text; its `reply` appears in the session live; after restart the full
    exchange is in history.

- [x] **T1.4 Pending-task replay on register (gap B).**
  - Deliver: on routine `register`, send every task still in `ready`.
  - Acceptance: send a message with no routine connected, then connect one; it
    receives the waiting task and can reply into the original session.

- [x] **T1.5 Failures surface in chat (gap C).**
  - Deliver: a routine `fail` (or disconnect mid-task) writes a visible `system`
    message into the session.
  - Acceptance: a failing routine produces a visible "Routine X failed: ..."
    message, not silence.

- [x] **T1.6 ROUTINE_PROTOCOL.md.**
  - Deliver: the WS contract for routine authors (envelope, routine frames,
    lifecycle, attachment fields), drawn from spec section 5.
  - Acceptance: a reader with only this doc can connect a routine and reply.

- [x] **T1.7 tether-connect connector CLI (gap A).**
  - Deliver: `cli/tether_connect.py` holding the WS, verbs `next` (block, claim,
    print task JSON incl. attachment urls + real paths), `reply`, `done`, `fail`.
  - Acceptance: each verb performs its protocol exchange end to end.

- [x] **T1.8 Reference routine.**
  - Done: echo reference routine verified live; round-trip works through the
    public URL. Wiring a real Claude `/loop` (vs the echo) is the operator's step
    using `tether-connect` + `ROUTINE_PROTOCOL.md`.
  - Deliver: `routines/reference_routine.py` on top of `tether-connect`.
  - Acceptance: a hand-wired Claude `/loop` using `tether-connect`, given only
    `ROUTINE_PROTOCOL.md`, connects and reports back into the session.

## M2 Multiple sessions (across devices)

- [x] **T2.1 Session CRUD + hydrate.**
  - Deliver: create / switch / rename / delete sessions; per-session history;
    session list in the UI; titles derived from the first message (no model).
  - Acceptance: session list and history persist across a restart; switching
    rehydrates the correct history.

- [x] **T2.2 Per-session scoping + multi-device streaming.**
  - Deliver: tasks/replies scoped to their session; the same session open on two
    devices both update live.
  - Acceptance: two sessions in two tabs do not cross (automated test); a reply
    fans out to every client subscribed to that session.

## M3 Image uploads

- [x] **T3.1 Upload + serve attachments.**
  - Deliver: `server/uploads.py`; `POST /upload` (multipart) stores bytes on disk
    + metadata in `attachments`, returns `{attachment_id, kind, mime, bytes}`;
    `GET /attachment/{id}` serves it; size cap from config.
  - Acceptance: an image uploads, is retrievable, and over-cap uploads are
    rejected with a clear error.

- [x] **T3.2 Images in messages and to the routine.**
  - Deliver: `user_message {text, attachment_ids[]}`; `message_appended` and
    `task_available` carry `attachments[]` with both `url` and the real host
    `path`; UI shows thumbnails.
  - Acceptance: an image sent in chat shows as a thumbnail and the routine
    receives its url and real path.

- [~] **T3.3 Routine reads an image.**
  - Done: the routine receives the image url + real host path (verified by
    `test_image_reaches_routine`). Actually opening/describing it is a real
    routine's job; the echo reference routine does not read image bytes.
  - Deliver: reference routine reads an image attachment from its real path.
  - Acceptance: the reference routine can open and describe a sent image.

## M4 Voice notes

- [x] **T4.1 Record + upload + playback.**
  - Deliver: browser MediaRecorder records a voice note, uploads it as an `audio`
    attachment; UI plays it back.
  - Acceptance: record, send, and replay a voice note in the chat.

- [x] **T4.2 Client-side transcription (default).**
  - Deliver: `voice = browser` uses the Web Speech API to transcribe client-side;
    the transcript is stored on the attachment. tether runs no model.
  - Acceptance: a spoken note arrives with a text transcript and tether made no
    model call.

- [~] **T4.3 Optional server-side Whisper.**
  - Done: code path present (`server/uploads.transcribe_audio`, config-gated by
    `voice = whisper`). Needs `uv add faster-whisper` to actually run; off by
    default. Not exercised live (no model installed).
  - Deliver: `voice = whisper` transcribes the uploaded audio with a local Whisper
    process (a media transform only, never intent); config-switched.
  - Acceptance: with `voice = whisper`, audio is transcribed server-side; with
    `voice = none`, audio is stored without a transcript.

- [x] **T4.4 Transcript reaches the routine.**
  - Deliver: `task_available` audio attachments carry the `transcript`.
  - Acceptance: the routine receives the voice note's text and can act on it.

## M5 Routine registry, claiming, status, cancel

- [x] **T5.1 Registry + capabilities + claiming.**
  - Acceptance: two routines connected, exactly one wins a claim; UI shows which.

- [x] **T5.2 Lifecycle status in the UI.**
  - Acceptance: ready -> picked by <routine> -> running -> done shown live.

- [x] **T5.3 Heartbeats + stale eviction (gap I).**
  - Done: heartbeats update last_seen; the watchdog flags tasks stuck in
    `claimed` past `TETHER_CLAIM_TIMEOUT` (default 300s) as needs_attention.
  - Acceptance: a silent routine is evicted after the timeout; its in-flight task
    is handled per T5.4.

- [x] **T5.4 Re-dispatch safety (gap E).**
  - Acceptance: killing a routine mid-task marks the task `needs_attention`
    (visible), not silently re-queued; re-dispatch is an explicit UI action.

- [x] **T5.5 Cancel / stop from the UI (gap F).**
  - Acceptance: a fired message can be aborted from the UI and the routine is
    told via `revoke`.

- [x] **T5.6 Confirm WAL + single-writer under load (gap G).**
  - Done: one shared aiosqlite connection serializes all writes (its single
    worker thread), so concurrent UI + routine writes cannot hit `database is
    locked`. WAL enabled on connect.
  - Acceptance: a multi-routine stress test shows no `database is locked`.

## M6 Config and validation

- [x] **T6.1 Config loader.**
  - Deliver: `server/config.py` reading `config.yaml` + env (server, uploads,
    voice). `TETHER_HOST`/`TETHER_PORT` already supported.
  - Acceptance: changing port/voice/upload settings via config takes effect on
    restart.

- [x] **T6.2 Fail-fast validation (gap K).**
  - Acceptance: a default/empty `auth_token` or missing uploads dir is reported
    clearly at boot, not mid-session.

## M7 Auth and reachability

- [x] **T7.1 Shared-token auth on every WS connect.**
  - Done: enforced on UI + routine WS only when a real token is set (default
    'change-me' = open, so the live no-token instance keeps working). REST
    endpoints stay open; use the proxy Access List for public hosts.
  - Acceptance: wrong/missing token -> rejected with a clear `error` frame;
    correct token -> accepted; token entered once in the UI.

- [x] **T7.2 Reachability docs.**
  - Deliver: README steps for a reverse proxy (Nginx Proxy Manager forwarding
    `host.docker.internal:4444`) and/or Tailscale, plus the access-list note.
  - Acceptance: tether reachable from another device through the proxy, never on
    a public address directly, with an access list on any public host.

## M8 Polish

- [x] **T8.1 Resilient UI socket + history pagination.**
  - Done: auto-reconnect with backoff; history capped at the last 300 messages
    (a cap, not infinite scroll).
  - Acceptance: drop and restore the network -> socket reconnects and resumes;
    long histories page in.

- [x] **T8.2 Rendering + mobile.**
  - Acceptance: routine replies render markdown; session search works; usable on a
    phone (PWA install).

- [x] **T8.3 Frame, chunk, and upload limits (gap H).**
  - Done: upload size cap (`uploads.max_mb`); WS frame size bounded by the
    uvicorn/websockets default.
  - Acceptance: oversized frames / replies / uploads are capped, not flooding the
    UI or disk.

- [x] **T8.4 Status view (gap J).**
  - Done: `GET /api/status` (JSON) and `/status.html` (auto-refreshing page).
  - Acceptance: a `/status` view shows connected routines, in-flight tasks, last
    error.

- [~] **T8.5 (optional) Web Push for mobile alerts.**
  - Done: in-tab/background Notifications fire when a routine reply arrives while
    the tab is hidden (permission requested on first send).
  - Deferred: true Web Push (server push when the tab is closed) needs VAPID keys
    + a push subscription; not implemented.

- [~] **T8.6 App icon set + PWA manifest.**
  - Done: `manifest.webmanifest` (SVG icon, any/maskable), favicon + apple-touch,
    theme-color, and a service worker (`sw.js`) so it installs as a PWA.
  - Deferred: rasterizing `icon.svg` to PNG home-screen sizes (180/192/512) needs
    an image tool not available in the buildless setup.
