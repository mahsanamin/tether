# tether routine protocol

How a routine talks to tether. tether is a pure bridge: it hands you the raw user
message + recent context, you do the work, you send a reply. tether runs no LLM
and never interprets the message.

The easy path is the **`tether-connect`** CLI (see below). This document is the
underlying contract if you want to speak it directly.

## Connection

Connect a WebSocket to `ws://<host>:4444/ws/routine` (use `wss://` behind TLS).
Every frame is JSON with this envelope:

```json
{ "type": "<type>", "id": "<uuid>", "session_id": "<id|null>", "ts": "<iso8601>", "payload": { } }
```

Only `type` and `payload` matter for routines; `id`/`ts`/`session_id` are
informational.

## Routine -> server

| type | payload | meaning |
|---|---|---|
| `register` | `{ routine_id, name, capabilities[], commands[]? }` | announce yourself; you then receive task pushes and a replay of any waiting tasks. Optional `commands[]` is a list of command names you can run (files + shell functions + aliases), shown in the `/c` picker |
| `claim` | `{ task_id }` | take ownership of a task |
| `reply` | `{ task_id, content }` | send a reply into the task's session (may be sent more than once to stream) |
| `status` | `{ task_id, state }` | `state` is `completed` or `failed` (add `reason` on failure; it shows in the chat) |
| `heartbeat` | `{}` | liveness (optional) |

## Server -> routine

| type | payload | meaning |
|---|---|---|
| `registered` | `{ ok, since }` | registration accepted |
| `task_available` | `{ task_id, session_id, text, attachments[], context[] }` | a task to claim: the raw message, its media, and recent session history |
| `claim_result` | `{ task_id, granted }` | whether your claim won (another routine may have taken it) |
| `revoke` | `{ task_id, reason }` | the task was pulled back (cancelled, etc.) |

`attachments[]` entries are `{ id, kind, mime, url, path, transcript? }`. `url` is
for fetching; `path` is the real host filesystem path, so a routine on the same
machine can open the file directly.

## The easy path: tether-connect

A Claude `/loop` does not naturally hold a socket open, so call the CLI instead:

```bash
tether-connect next                  # block until a task, claim it, print JSON
tether-connect reply <task_id> TEXT  # send a reply into the session
tether-connect done <task_id>        # mark completed
tether-connect fail <task_id> WHY    # mark failed (surfaces in the chat)
```

A routine loop is then trivial:

1. `task=$(tether-connect next)` and parse the JSON (`task_id`, `text`, `context`).
2. Do the work (this is where your full Claude reads `text`, the attachments, and
   the context, and figures out intent).
3. `tether-connect reply "$task_id" "<result>"` then `tether-connect done "$task_id"`.

See `routines/reference_routine.py` for a minimal working example (it just
acknowledges, so the chat shows delivery ticks rather than an echo).

## Running commands from the chat (the shell routine)

tether never runs commands itself (the guardrail). To run commands from the chat
window, run a routine that executes them and replies with the output:

```bash
uv run python routines/shell_routine.py            # every message is run as a command
uv run python routines/shell_routine.py --prefix '$ '   # only messages starting with '$ '
```

Then typing `echo hello && whoami` in the chat returns the output in a code
block, in the same thread.

DANGER: this is arbitrary remote command execution on your machine. Only run it
on a private tether. Before connecting it to a publicly reachable instance, set
`server.auth_token` (config.yaml) and keep an NPM Access List on the public host.
Each message runs with a real terminal (pty) in a fresh shell (so `cd` does not
persist; use `cd /x && cmd`). Quick commands return their output. A command that
keeps running past a short grace window (an interactive / remote-control session,
e.g. a wrapper that opens `claude` in a directory) is left **running in the
background with its terminal**, and you drive it from the Claude app, no `&`
needed and nothing is killed. End a command with `&` to detach it immediately
without waiting for output.
