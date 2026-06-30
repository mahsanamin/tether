---
name: tether-build
description: Execute the next unchecked task in tether's task-sequence.md, end to end, following the project rules. Use when the user wants to start or continue building tether ("do the next task", "continue tether", "build M1", "pick up the next task", "start coding tether"). Reads the design and rules, picks the first unchecked task, implements only that task within the pinned stack, gates on its acceptance criteria, then checks it off and reports. Project-scoped to the tether repo.
---

# tether-build

Drive one task of the tether build, the right way. tether is a broker that never
thinks or acts (see `CLAUDE.md`); keep that line while you build.

## Procedure

1. **Load context (in order).** Read `CLAUDE.md`, then `specs.md` for the area you
   are about to touch, `docs/tech-stack.md`, and the relevant files in
   `docs/ai-rules/` (always `00-process.md` and `01-guardrails.md`, plus
   `02-python-backend.md` or `03-frontend.md` for the layer).

2. **Pick the task.** Open `task-sequence.md`. Take the **first unchecked** task.
   Do only that one. If the user named a later task, tell them what unchecked tasks
   come before it and confirm before skipping.

3. **Restate acceptance.** Write out the task's Acceptance lines as your definition
   of done before coding. If acceptance is ambiguous or needs an undocumented
   decision, stop and ask. Do not invent scope.

4. **Implement within the stack.** Build only with what is in `docs/tech-stack.md`.
   To add any dependency, update `docs/tech-stack.md` first with a one-line reason.
   Match the envelope, message types, and data model in `specs.md` sections 5 and
   6 exactly. tether runs no LLM; keep it a pure bridge (see guardrails).

5. **Prove it.** Add or update a test in `tests/` that maps to the acceptance,
   when feasible. Run `uv run ruff format .`, `uv run ruff check .`, and
   `uv run pytest`. All must be clean.

6. **Verify against the guardrail.** Before committing, run the
   `tether-guardrail-reviewer` subagent on the change (or self-check with the
   litmus test). Resolve any flagged issue.

7. **Close out.** Check the task box in `task-sequence.md`, add a one-line note of
   anything learned under it, update the `## Now` pointer to the next task, update
   `specs.md` or `docs/tech-stack.md` if the design or stack changed, then commit
   and merge. Report what was done and what the next task is.

## Rules of the road

- One task at a time. Acceptance is the gate.
- No em dashes or en dashes in code, comments, or docs.
- If a change would make tether decide or act, it is wrong: that work is a
  routine's job, not tether's.
