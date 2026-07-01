"""tether-connect: a thin WebSocket client so a routine speaks plain verbs.

A Claude routine does not naturally hold a WebSocket open, so it calls these
instead of the protocol:

  tether-connect next                   block until a task, claim it, print JSON
  tether-connect reply <task_id> TEXT   send a reply into the session
  tether-connect done <task_id>         mark the task completed
  tether-connect fail <task_id> WHY     mark the task failed (surfaces in chat)

The JSON printed by `next` includes task_id, session_id, text, and recent
context, plus any attachment urls + real host paths.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import websockets

DEFAULT_URL = "ws://127.0.0.1:4444/ws/routine"


def _resolve_token() -> str:
    """Token for the routine to authenticate. Prefer TETHER_TOKEN; otherwise read
    config.yaml's auth_token, so a launchd agent needs no secret in its plist
    (config.yaml is gitignored, the plist is committed)."""
    tok = os.environ.get("TETHER_TOKEN", "")
    if tok:
        return tok
    try:
        from server import config as config_mod

        root = Path(__file__).resolve().parent.parent
        cfg_tok = config_mod.load(root)["server"]["auth_token"]
        if cfg_tok and cfg_tok != "change-me":
            return cfg_tok
    except Exception:
        pass
    return ""


TOKEN = _resolve_token()


async def next_task(
    url: str = DEFAULT_URL, name: str = "routine", commands: list | None = None
) -> dict:
    """Register, wait for a task, claim it, return its payload. `commands` is an
    optional list of command names this routine can run, surfaced in the /c
    picker (tether just serves it; the routine is what executed the shell to
    gather it)."""
    async with websockets.connect(url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "register",
                    "payload": {
                        "routine_id": name,
                        "name": name,
                        "capabilities": [],
                        "commands": commands or [],
                        "token": TOKEN,
                    },
                }
            )
        )
        pending: dict[str, dict] = {}
        while True:
            msg = json.loads(await ws.recv())
            t = msg.get("type")
            p = msg.get("payload", {})
            if t == "task_available":
                pending[p["task_id"]] = p
                await ws.send(
                    json.dumps(
                        {
                            "type": "claim",
                            "payload": {"task_id": p["task_id"], "token": TOKEN},
                        }
                    )
                )
            elif t == "claim_result" and p.get("granted"):
                return pending.get(p["task_id"], {"task_id": p["task_id"]})


async def _send(url: str, frame: dict) -> None:
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps(frame))
        await asyncio.sleep(0.3)  # let the server process before the socket closes


async def reply(url: str, task_id: str, text: str) -> None:
    await _send(
        url,
        {
            "type": "reply",
            "payload": {"task_id": task_id, "content": text, "token": TOKEN},
        },
    )


async def done(url: str, task_id: str) -> None:
    await _send(
        url,
        {
            "type": "status",
            "payload": {"task_id": task_id, "state": "completed", "token": TOKEN},
        },
    )


async def fail(url: str, task_id: str, why: str) -> None:
    await _send(
        url,
        {
            "type": "status",
            "payload": {
                "task_id": task_id,
                "state": "failed",
                "reason": why,
                "token": TOKEN,
            },
        },
    )


def main() -> None:
    ap = argparse.ArgumentParser(prog="tether-connect")
    ap.add_argument("--url", default=DEFAULT_URL)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pn = sub.add_parser("next")
    pn.add_argument("--name", default="routine")
    pr = sub.add_parser("reply")
    pr.add_argument("task_id")
    pr.add_argument("text")
    pd = sub.add_parser("done")
    pd.add_argument("task_id")
    pf = sub.add_parser("fail")
    pf.add_argument("task_id")
    pf.add_argument("why")
    args = ap.parse_args()

    if args.cmd == "next":
        print(json.dumps(asyncio.run(next_task(args.url, args.name))))
    elif args.cmd == "reply":
        asyncio.run(reply(args.url, args.task_id, args.text))
    elif args.cmd == "done":
        asyncio.run(done(args.url, args.task_id))
    elif args.cmd == "fail":
        asyncio.run(fail(args.url, args.task_id, args.why))


if __name__ == "__main__":
    main()
