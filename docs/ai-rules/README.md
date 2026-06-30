# tether: AI Rules

Exact rules a coding session (human or LLM) must follow when working on tether.
These rules cover **only** the technologies pinned in
[`../tech-stack.md`](../tech-stack.md). If a tool is not in the tech stack, there
is no rule for it because it should not be used.

## Read order before any work

1. [`../../README.md`](../../README.md) - what tether is and why.
2. [`../../specs.md`](../../specs.md) - the design: architecture, protocol, data
   model, guardrails.
3. [`../tech-stack.md`](../tech-stack.md) - what you may build with.
4. This folder: [`00-process.md`](./00-process.md) first, then the rule file for
   the layer you are touching.
5. [`../../task-sequence.md`](../../task-sequence.md) - pick the first unchecked
   task and do only that.

## The rule files

- [`00-process.md`](./00-process.md) - how work proceeds (one task at a time,
  acceptance-gated, no scope creep). Always applies.
- [`01-guardrails.md`](./01-guardrails.md) - the non-negotiable architecture line
  (tether never thinks or acts). Always applies.
- [`02-python-backend.md`](./02-python-backend.md) - rules for the Python / FastAPI
  / SQLite / WebSocket / uploads backend. Load when touching the backend.
- [`03-frontend.md`](./03-frontend.md) - rules for the buildless web UI. Load when
  touching the frontend.

Load only the layer rules relevant to the task in front of you.
