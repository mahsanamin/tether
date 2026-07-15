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
import re
import select
import subprocess
import threading
import time

from cli.tether_connect import DEFAULT_URL, done, fail, next_task, reply

MAX_OUTPUT = 4000
# How long to keep capturing a command's output before treating it as a
# background session. Longer = the chat shows more of what a launch actually did
# (repo resolved, worktree made, tab opened) before it detaches. Env-tunable.
GRACE_S = int(os.environ.get("TETHER_GRACE_S", "20"))

# Strip ANSI/VT escapes and stray control bytes so captured terminal output reads
# as clean text in the chat instead of a mess of color codes and cursor moves.
# tether never interprets this; the routine just tidies the raw bytes it relays.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI ... sequences (colors, cursor moves)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... (window titles etc.)
    r"|\x1b[@-Z\\-_]"  # two-char escapes
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"  # other control bytes (keep \t \n \r)
)


def _clean(text: str) -> str:
    """Remove terminal escapes and normalize carriage returns for chat display."""
    return _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def list_commands() -> list[str]:
    """The command surface this routine can run: executable files on PATH plus the
    user's shell functions and aliases. Gathered once at startup (via zsh, which
    this routine is allowed to do) and reported to the server for the /c picker, so
    function-only commands like aa_g_worktree_list show up too, not just files."""
    try:
        out = subprocess.run(
            [
                "/bin/zsh",
                "-ic",
                # rehash first: zsh's command hash can predate PATH dirs added late
                # in .zshrc (e.g. project_scripts), which would otherwise be missing.
                "rehash; print -rl -- ${(k)commands} ${(k)functions} ${(k)aliases}",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    # drop internal (leading-underscore) helpers; dedupe + sort
    return sorted({n for n in out.split() if n and not n.startswith("_")})


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
    # Run through an interactive zsh (`zsh -i -c`) so the user's shell functions
    # and aliases resolve, not just executable files. Plenty of commands the user
    # runs (e.g. aa_g_worktree_list) are zsh functions from their .zshrc; a plain
    # `sh -c` could never find them. Sourcing .zshrc adds no stdout noise (verified).
    proc = subprocess.Popen(
        ["/bin/zsh", "-i", "-c", command],
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
        out = _clean(result.get("output") or "").strip()
        # Show the LATEST output (the newest stage a launch reached), not the head.
        if len(out) > MAX_OUTPUT:
            out = "... (earlier output trimmed)\n" + out[-MAX_OUTPUT:]
        body = ("\n```\n" + out + "\n```") if out else ""
        note = (
            "\n\n_Note: this is the setup output. If it launched Claude in a zellij "
            "tab, that session keeps running there / in the Claude app; its own work "
            "does not stream back here._"
        )
        await reply(
            url,
            task_id,
            f"Still running in the background (pid {result['pid']}) after {GRACE_S}s. "
            "Here is what it printed so far:" + body + note,
        )
    else:
        out = _clean(result.get("output") or "").strip()
        out = out or f"(no output, exit code {result['code']})"
        if len(out) > MAX_OUTPUT:
            out = out[:MAX_OUTPUT] + "\n... (truncated)"
        await reply(url, task_id, "```\n" + out + "\n```")
    await done(url, task_id)


async def main(url: str, prefix: str) -> None:
    note = f" (only messages starting with {prefix!r})" if prefix else ""
    commands = list_commands()
    print(
        f"shell routine on {url}; each message runs as a command{note}. "
        f"reported {len(commands)} commands for the /c picker."
    )
    while True:
        try:
            task = await next_task(url, name="shell", commands=commands)
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
