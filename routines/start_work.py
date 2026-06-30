"""start-work routine: type a task in the chat and it starts a Claude Code session
on this machine for that task, which you then pick up in the Claude app (Remote
Control) or in Claude Code. No shell, no '$' prefix, no quoting, just a task.

tether still executes nothing itself; this routine launches the session via a
launcher command of your choice (--launcher): any command on your PATH invoked as
`<launcher> <dir> <prompt>` that opens a coding session, e.g. a small wrapper
around `claude`.

Message format:
  <task>              -> session in the default dir (--dir), seeded with <task>
  /abs/path <task>    -> session in that repo (use /d to insert the path first)

Run it (instead of the shell routine):
  uv run python routines/start_work.py --dir ~/projects --launcher claude-session
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import threading

from cli.tether_connect import DEFAULT_URL, done, fail, next_task, reply


def launch_detached_pty(argv: list[str]) -> int:
    """Launch argv in its own session with a real TTY (the launcher runs an
    interactive claude session), detached so it persists. Output is not captured."""
    master, slave = os.openpty()
    proc = subprocess.Popen(
        argv,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)

    def _drain() -> None:
        try:
            while os.read(master, 4096):
                pass
        except OSError:
            pass
        finally:
            try:
                os.close(master)
            except OSError:
                pass

    threading.Thread(target=_drain, daemon=True).start()
    return proc.pid


async def run_one(url: str, task: dict, default_dir: str, launcher: str) -> None:
    task_id = task["task_id"]
    text = (task.get("text") or "").strip()
    if not text:
        await done(url, task_id)
        return

    work_dir, prompt = default_dir, text
    parts = text.split(None, 1)
    if parts and parts[0].startswith("/") and os.path.isdir(parts[0]):
        work_dir = parts[0]
        prompt = parts[1] if len(parts) > 1 else ""

    work_dir = os.path.expanduser(work_dir)
    if not os.path.isdir(work_dir):
        await fail(url, task_id, f"not a directory: {work_dir}")
        return
    if prompt.startswith("-"):
        # don't let the task be read as a flag by the launcher (argv injection).
        # The prompt is passed as a single positional, never split into flags.
        await fail(
            url, task_id, "the task cannot start with '-' (it would look like a flag)"
        )
        return

    argv = [launcher, work_dir]
    if prompt:
        argv.append(prompt)
    try:
        pid = await asyncio.to_thread(launch_detached_pty, argv)
        seeded = f" for: {prompt}" if prompt else ""
        await reply(
            url,
            task_id,
            f"started a Claude Code session in {work_dir} (pid {pid}){seeded}. "
            "Pick it up in the Claude app (Remote Control) or in Claude Code.",
        )
        await done(url, task_id)
    except Exception as e:  # noqa: BLE001
        await fail(url, task_id, f"could not start session: {e}")


async def main(url: str, default_dir: str, launcher: str) -> None:
    print(
        f"start-work routine connected to {url}; default dir {default_dir}, "
        f"launcher {launcher}. Type a task to open a Claude Code session."
    )
    while True:
        task = await next_task(url, name="start-work")
        await run_one(url, task, default_dir, launcher)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument(
        "--dir", default=os.path.expanduser("~"), help="default work directory"
    )
    ap.add_argument(
        "--launcher",
        default="claude-session",
        help="session launcher command, invoked as <launcher> <dir> <prompt>",
    )
    args = ap.parse_args()
    asyncio.run(main(args.url, os.path.expanduser(args.dir), args.launcher))
