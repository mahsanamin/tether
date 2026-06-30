# tether: Tech Stack

The pinned, authoritative list of technologies for tether. The rules in
`docs/ai-rules/` apply only to what is listed here. Do not introduce a dependency
or tool that is not on this list without first updating this file and saying why.

tether is a **pure bridge with no LLM of its own**. It carries messages and media
between you and Claude routines; the routine is the brain.

## Decided

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | Strong async + WebSocket story; same machine as the routines |
| Runtime / packaging | `uv` | Fast, locked, reproducible installs; one-command run; no container |
| Web + realtime | FastAPI + Starlette WebSockets | First-class native WebSockets, HTTP, and static serving in one process |
| ASGI server | `uvicorn` | Standard FastAPI server |
| Storage | SQLite via `aiosqlite`, WAL mode | Single-file, zero-admin, survives restarts; WAL for concurrent writes |
| Attachments | Files on the local disk + metadata rows in SQLite | Real host paths a native routine can open directly (no container translation) |
| Frontend | Buildless: HTML + vanilla JS (ES modules) + CSS | No npm, no build step; one WebSocket; light and swappable later |
| Voice capture | Browser `MediaRecorder` API | Record voice notes client-side, no server dependency |
| Voice transcription | Web Speech API (default, client-side) or `faster-whisper` native (optional) | A media transform (audio to text), never intent. Default keeps tether model-free |
| Config | YAML (`pyyaml`) + environment variables | One `config.yaml`; secrets in env only; `TETHER_HOST`/`TETHER_PORT` overrides |
| Always-on | `launchd` user agent (macOS) | Native autostart + restart; lighter than a daemonized container |
| Reachability | Reverse proxy (Nginx Proxy Manager) and/or Tailscale | tether binds `127.0.0.1`; proxy/tailnet provides private remote access |
| Routine bridge | `tether-connect` CLI + `websockets` client | Lets a Claude routine use plain verbs instead of speaking the protocol |
| Tests | `pytest` + `httpx` / `websockets` test clients | Async-friendly, drives the real WS and upload paths |
| Lint + format | `ruff` | One tool for both; fast |

## No LLM in tether (decided)

There is deliberately **no LLM library and no model call** in tether. An earlier
design had a small "normalizer" model clean each message; that was removed. The
consumer is a full Claude routine, and a weak model upstream of a strong one only
loses fidelity and adds latency. tether hands the routine the **raw message +
media + context**, and the routine extracts intent. The only model that may ever
run near tether is speech-to-text (Whisper), purely as an audio-to-text media
transform, off by default in favor of client-side Web Speech.

## Run model: native, not Docker (decided)

tether runs as a single native Python process, started with `uv` and kept alive by
`launchd`. Docker is intentionally not used. Reasons:

- **Shared host filesystem.** Native tether stores attachments at real host paths,
  and any path referenced in chat resolves identically for a routine on the same
  machine. A container would hide files behind volume mounts and path translation.
- **Direct, real-time connection.** Routines and tether talk over flat `localhost`
  with no container network boundary.
- **GPU.** An optional local model (Ollama, or Whisper) needs the Mac's Metal GPU,
  which Docker Desktop on macOS cannot pass through.
- **Low value of isolation.** tether is one process, one SQLite file, one
  attachments folder. `uv` already gives locked, reproducible dependencies.

Note on reaching tether from a Dockerized reverse proxy (Nginx Proxy Manager): on
Docker Desktop for Mac the container reaches the host loopback via
`host.docker.internal:4444`, so tether stays on `127.0.0.1` (no `0.0.0.0`).

Docker is reconsidered only if tether ever moves to a headless Linux box. Out of
scope (see `specs.md` section 12).

## Explicitly not used

- **Any LLM library / model call inside tether** (see above). No `litellm`, no
  normalizer.
- **Docker / docker-compose** (see above).
- **Node / npm / a frontend build step** (frontend stays buildless).
- **Socket.IO** (native WebSockets are enough).
- **Redis, Postgres, or any message broker** (SQLite + the in-process hub suffice).
- **An ORM** (small, explicit SQL via `aiosqlite`).
- **Chat-platform SDKs** (Discord/Telegram/WhatsApp): rejected for privacy; the
  client is ours.
