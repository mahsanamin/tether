"""Minimal reference routine: echoes each task back, proving the round trip.

Run it on the same machine as tether:
    uv run python routines/reference_routine.py [--url ws://127.0.0.1:4444/ws/routine]

This echo is the walking-skeleton proof. Replace the body with a real Claude
`/loop` or agent (which reads `task["text"]`, its attachments and context, does
the work, and calls `reply` + `done`) for actual use.
"""

from __future__ import annotations

import argparse
import asyncio

from cli.tether_connect import DEFAULT_URL, done, next_task


async def main(url: str) -> None:
    print(f"reference routine connected to {url}; waiting for tasks...")
    while True:
        task = await next_task(url, name="reference")
        # Acknowledge only (claim + done) so the chat shows delivery ticks, not an
        # echo. A real Claude routine replaces this with `reply` + `done`.
        print(f"got task {task.get('task_id')}: {task.get('text', '')!r}")
        await done(url, task["task_id"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    asyncio.run(main(ap.parse_args().url))
