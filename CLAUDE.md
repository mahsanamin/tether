# CLAUDE.md: tether

Read this first, every session, before any work.

## What tether is

A private, always-on **bridge**. You send a message (text, voice note, or image)
from any device, and a Claude routine on the machine picks it up, does the work,
and reports back into the same chat, live. tether runs **no LLM**: it hands the
routine the raw message + media + context, and the routine extracts intent.

**tether is transport + presentation. The brain and the hands live in the
routines. tether never thinks and never acts.** This one line is the contract.

## The non-negotiable guardrail

Before writing anything, apply this test:

> Does this change make a decision, interpret intent, or touch anything outside
> tether's own message/attachment store? If yes, it belongs in a routine, not in
> tether.

Hard nos: no executing commands or shell, no intent/LLM model or agent loop
inside tether, no learned/persistent agent memory, no chat-platform bridges (the
only UI is the private web client). The only model tether may ever run is
**speech-to-text** for voice notes, as a media transform, never to interpret or
decide, and off by default in favor of client-side transcription. Full detail in
`docs/ai-rules/01-guardrails.md` and `specs.md` sections 14 and 15.

## How to work

1. Read in order: this file, `README.md`, `specs.md`, `docs/tech-stack.md`, then
   `docs/ai-rules/` (its `README.md` first).
2. Open `task-sequence.md`, take the **first unchecked task**, and do only that.
3. Build within the stack in `docs/tech-stack.md`. Do not add a dependency or tool
   that is not listed there without updating `docs/tech-stack.md` first.
4. Meet every line under the task's **Acceptance** before checking the box. Prove
   it with a test in `tests/` when you can.
5. Run `uv run ruff format .`, `uv run ruff check .`, `uv run pytest`. Then check
   the box, commit, merge, and move on.
6. If a needed decision is not written down, stop and raise it. No scope creep.

The `tether-build` skill runs this loop for you. The `tether-guardrail-reviewer`
subagent checks a change against the guardrail and the stack before you commit.

## Stack in one line

Native Python 3.12+ run with `uv` (no Docker), FastAPI + Starlette WebSockets,
SQLite via `aiosqlite` (WAL), attachments on disk at real host paths, a buildless
vanilla-JS frontend (MediaRecorder for voice notes), **no LLM in tether**, kept
alive by `launchd`, reached over Tailscale or a reverse proxy. Authority:
`docs/tech-stack.md`.

## Doc roles (keep them honest)

- `README.md`: what and why (narrative, stable).
- `specs.md`: the design (architecture, protocol, data model, guardrails). Not a
  build spec to execute top to bottom.
- `task-sequence.md`: the actual tasks, executed one at a time. Source of truth
  for what to build next.
- `docs/tech-stack.md`: the only allow-list of technologies.
- `docs/ai-rules/`: the exact coding rules, scoped per layer.

If work changes the design, update `specs.md`; if it changes the stack, update
`docs/tech-stack.md`. The docs must always match reality.

## Writing style

No em dashes or en dashes anywhere (code, comments, docs, commits). Use commas,
colons, parentheses, or hyphens.
