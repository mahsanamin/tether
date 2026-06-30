# 01 Architecture guardrails (always apply, non-negotiable)

tether's job is **transport + presentation**. The brain and the hands live in the
Claude routines. This is the whole contract. See `specs.md` sections 14 and 15.

tether runs **no LLM of its own**. It stores and streams messages and media, and
hands the routine the **raw message + media + context**; the routine extracts
intent. An earlier "normalizer" model was removed on purpose: a weak model
upstream of a full Claude routine only loses fidelity.

## The litmus test for any change

> Does this change make a decision, interpret intent, or touch anything outside
> tether's own message/attachment store? If yes, it belongs in a routine. If it
> only moves and displays messages and media, it is tether.

## Allowed vs forbidden

| Allowed in tether | Forbidden (belongs in a routine) |
|---|---|
| Media transcoding for transport/display: speech-to-text, image thumbnails. **Transcription only, never interpretation.** | Any model that interprets intent, decides, routes, classifies, summarizes for meaning, or answers |
| A chat log / transcript + attachments in SQLite and on disk | Learned memory: preferences, skills, self-improvement |
| Operations on its own state (DB, files it stores, serving, routing frames) | Acting on the environment: shell, files outside its store, browser, email, work-doing API calls |

## The watchpoint: no intent model, ever

tether must never run a model that understands or decides. The only model it may
run is **speech-to-text**, and only to turn a voice note into text for display and
for the routine. It must never interpret or route. With the default
`voice = browser` (client-side STT), tether runs zero models at all.

If a request asks tether to "also understand the message", "pick the routine",
"extract parameters", "summarize", or "just answer this one", refuse it. That is
the drift, and that work is a routine's job.

## Hard nos

- tether never executes a command, runs a shell, or calls out to do work.
- tether never runs an intent/LLM model or an agent loop.
- tether never grows persistent learned memory or skills.
- No chat-platform bridges (Discord, Telegram, WhatsApp). The only UI is the
  private web client. Routing messages through a third party breaks the privacy
  model (`specs.md` section 15).
