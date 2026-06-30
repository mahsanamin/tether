# 00 Process rules (always apply)

1. **One task at a time.** Take the first unchecked task in
   `task-sequence.md`. Do only that task. Do not start the next until this one is
   checked off and merged.
2. **Acceptance is the gate.** Every line under a task's **Acceptance** must hold
   before you check the box. Prove it with a test in `tests/` whenever you can.
3. **Stay inside the stack.** Build only with what is in `docs/tech-stack.md`. To
   add any dependency or tool, update `docs/tech-stack.md` first, with a one-line
   reason, then proceed.
4. **No scope creep.** If a task needs a decision that is not written down, stop
   and raise it. Do not invent features, endpoints, or config.
5. **Keep the docs honest.** If the work changes the design, update `specs.md`. If
   it changes the stack, update `docs/tech-stack.md`. The two narrative files
   (`README.md`, `specs.md`) plus `task-sequence.md` must always match reality.
6. **Small, reviewable changes.** Each task is one focused change set. Run
   `uv run ruff check .`, `uv run ruff format .`, and `uv run pytest` before
   committing. Commit, then merge.
7. **Writing style.** No em dashes or en dashes in code, comments, or docs. Use
   commas, colons, parentheses, or hyphens.
8. **When in doubt, re-read [`01-guardrails.md`](./01-guardrails.md).** If a change
   would make tether think or act, it is wrong by definition.
