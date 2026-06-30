"""Config: defaults <- config.yaml <- environment. No secrets in code.

Auth is optional: a default/empty token means open access (dev). Set a real
token (config.yaml server.auth_token or TETHER_AUTH_TOKEN) to require it on every
WebSocket connect.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "server": {"bind": "127.0.0.1", "port": 4444, "auth_token": "change-me"},
    "uploads": {"dir": "./data/attachments", "max_mb": 25},
    "voice": {"provider": "browser", "whisper_url": "http://127.0.0.1:9000"},
}


def load(root: Path) -> dict[str, Any]:
    cfg = {section: dict(vals) for section, vals in DEFAULTS.items()}
    path = root / "config.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        for section, vals in data.items():
            if isinstance(vals, dict):
                cfg.setdefault(section, {}).update(vals)

    cfg["server"]["bind"] = os.environ.get("TETHER_HOST", cfg["server"]["bind"])
    cfg["server"]["port"] = int(os.environ.get("TETHER_PORT", cfg["server"]["port"]))
    cfg["server"]["auth_token"] = os.environ.get(
        "TETHER_AUTH_TOKEN", cfg["server"]["auth_token"]
    )
    if os.environ.get("TETHER_UPLOAD_DIR"):
        cfg["uploads"]["dir"] = os.environ["TETHER_UPLOAD_DIR"]
    cfg["uploads"]["max_mb"] = int(
        os.environ.get("TETHER_MAX_MB", cfg["uploads"]["max_mb"])
    )
    cfg["voice"]["provider"] = os.environ.get("TETHER_VOICE", cfg["voice"]["provider"])
    # bridge voice provider to the env that uploads.transcribe_audio reads
    os.environ["TETHER_VOICE"] = cfg["voice"]["provider"]
    return cfg


def validate(cfg: dict[str, Any], upload_dir: Path) -> list[str]:
    """Return human-readable warnings; the caller decides how loud to be."""
    warnings: list[str] = []
    if cfg["server"]["auth_token"] in ("", "change-me"):
        warnings.append(
            "auth is OFF (no token): anyone who can reach this server can run "
            "commands on this machine. Fine when access is restricted to a "
            "trusted network (Tailscale / an NPM Access List); otherwise set a "
            "token (config.yaml server.auth_token or TETHER_AUTH_TOKEN)."
        )
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        warnings.append(f"uploads dir {upload_dir} is not writable: {e}")
    return warnings


def auth_required(token: str) -> bool:
    return token not in ("", "change-me")
