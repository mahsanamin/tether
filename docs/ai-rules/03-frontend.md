# 03 Frontend rules

Applies to `web/`. Covers only the stack in `docs/tech-stack.md`: buildless HTML +
vanilla JS (ES modules) + CSS, served as static assets by the backend.

## Buildless, always

- No npm, no bundler, no build step, no transpiler. Files in `web/` are served
  as-is and run directly in the browser.
- Use native ES modules (`<script type="module">`) and modern browser APIs. No
  framework in v1. (Preact/htmx may be considered later, but only via a tech-stack
  update, and the backend contract must not change.)
- Keep it to three files where possible: `index.html`, `app.js`, `style.css`.

## One WebSocket

- The UI holds **one** WebSocket connection (per spec section 5). Route all live
  traffic through it. Use REST only to hydrate history on first load.
- Match the envelope and message types in `specs.md` section 5 exactly. Do not
  invent frame shapes on the client.
- Reconnect with backoff (lands in T8.1); on reconnect, rehydrate from REST then
  resume the live feed.

## Behavior and state

- The client is a thin view: it sends `user_message`, renders `message_appended`
  and `task_status`, and shows session lists. It makes no decisions and runs no
  model. (See `01-guardrails.md`.)
- Keep the auth token in browser storage; never embed secrets or provider keys in
  the frontend.
- Render routine replies as markdown (T8.2). Show image thumbnails and voice-note
  playback for attachments (M3, M4).

## Style

- Plain, readable CSS. Mobile-friendly layout (usable on a phone over Tailscale).
- No em dashes or en dashes in UI copy or comments.
