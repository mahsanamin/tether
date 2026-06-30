"""Command-runner routine: runs each chat message as a command on the host and
replies with the output. This is how you run commands from the chat WITHOUT
tether ever executing anything itself (tether stays a pure bridge).

DANGER: arbitrary remote command execution. Only run on a private tether: set
server.auth_token (config.yaml) and/or an NPM Access List on the public host.

Run it:
    uv run python routines/shell_routine.py
    uv run python routines/shell_routine.py --prefix '$ '   # only '$ '-prefixed

Every command runs with a real terminal (pty). Quick commands return their output
here. A command that does not finish within a grace window (an interactive or
remote-control session, e.g. a wrapper that opens claude) is left running in the
background with its terminal, and you drive it from the Claude app; no '&' needed. End a
command with '&' to detach immediately without waiting. `cd` does not persist
across messages (use `cd /x && cmd`).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import select
import subprocess
import threading
import time

from cli.tether_connect import DEFAULT_URL, done, fail, next_task, reply

MAX_OUTPUT = 4000
GRACE_S = 10  # wait this long for output before treating it as a background session


def _drain_master(master: int) -> None:
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


def run_in_pty(command: str, force_detach: bool) -> dict:
    """Run `command` with a real TTY. Capture output until it exits or GRACE_S
    passes; if still running, leave it in the background (it persists) and say so."""
    master, slave = os.openpty()
    proc = subprocess.Popen(
        command,
        shell=True,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)

    chunks: list[str] = []
    detached = force_detach
    if not force_detach:
        deadline = time.monotonic() + GRACE_S
        while True:
            if proc.poll() is not None:
                while True:  # drain remaining buffered output
                    r, _, _ = select.select([master], [], [], 0.1)
                    if master not in r:
                        break
                    try:
                        data = os.read(master, 4096)
                    except OSError:
                        data = b""
                    if not data:
                        break
                    chunks.append(data.decode(errors="replace"))
                break
            if time.monotonic() >= deadline:
                detached = True
                break
            r, _, _ = select.select([master], [], [], 0.5)
            if master in r:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data.decode(errors="replace"))

    if detached:
        threading.Thread(target=_drain_master, args=(master,), daemon=True).start()
        return {"detached": True, "pid": proc.pid, "output": "".join(chunks)}

    rc = proc.wait()
    try:
        os.close(master)
    except OSError:
        pass
    return {"detached": False, "code": rc, "output": "".join(chunks)}


async def run_one(url: str, task: dict, prefix: str) -> None:
    task_id = task["task_id"]
    text = (task.get("text") or "").strip()
    if not prefix and text.startswith("$"):
        text = text[1:].lstrip()  # allow an optional leading "$" / "$ " prompt
    if prefix:
        tight = prefix.rstrip()  # accept the prefix with or without a trailing space
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
        elif tight and tight != prefix and text.startswith(tight):
            text = text[len(tight) :].strip()
        else:
            await reply(
                url,
                task_id,
                f"not a command, so I did not run it. Start the message with "
                f"`{tight}` (or pick one with /c) to run a command.",
            )
            await done(url, task_id)
            return
    force_detach = text.endswith("&")
    if force_detach:
        text = text[:-1].strip()
    if not text:
        await done(url, task_id)
        return
    try:
        result = await asyncio.to_thread(run_in_pty, text, force_detach)
    except Exception as e:  # noqa: BLE001
        await fail(url, task_id, f"command error: {e}")
        return

    if result["detached"]:
        out = (result.get("output") or "").strip()
        tail = ("\n```\n" + out[:MAX_OUTPUT] + "\n```") if out else ""
        await reply(
            url,
            task_id,
            f"running with a terminal in the background (pid {result['pid']}). "
            "Interactive / remote-control sessions stay "
            "open; drive them from the Claude app." + tail,
        )
    else:
        out = (result.get("output") or "").strip()
        out = out or f"(no output, exit code {result['code']})"
        if len(out) > MAX_OUTPUT:
            out = out[:MAX_OUTPUT] + "\n... (truncated)"
        await reply(url, task_id, "```\n" + out + "\n```")
    await done(url, task_id)


async def main(url: str, prefix: str) -> None:
    note = f" (only messages starting with {prefix!r})" if prefix else ""
    print(f"shell routine on {url}; each message runs as a command{note}.")
    while True:
        try:
            task = await next_task(url, name="shell")
            await run_one(url, task, prefix)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            # The server restarting (or not up yet) drops our socket. Don't die:
            # wait and reconnect, so a server bounce never takes the routine, or
            # any session it launched, down with it.
            print(f"shell routine: connection lost ({e!r}); reconnecting in 2s")
            await asyncio.sleep(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--prefix", default="", help="only run messages with this prefix")
    args = ap.parse_args()
    asyncio.run(main(args.url, args.prefix))
