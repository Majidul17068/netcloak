"""Persist backups of everything we change so `off` can fully revert."""
from __future__ import annotations

import json
import os
from pathlib import Path


def state_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("PROGRAMDATA", str(Path.home()))) / "netcloak"
    else:
        base = Path("/var/lib/netcloak")
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base
        except PermissionError:
            base = Path.home() / ".netcloak"
    base.mkdir(parents=True, exist_ok=True)
    return base


def state_path() -> Path:
    return state_dir() / "state.json"


def load_state() -> dict:
    path = state_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            return {}
    return {}


def save_state(state: dict) -> None:
    state_path().write_text(json.dumps(state, indent=2))


def clear_state() -> None:
    path = state_path()
    if path.exists():
        path.unlink()


def has_state() -> bool:
    return state_path().exists()


# --------------------------------------------------------------------------- #
# tunnel state (VPN / Tor) — tracked separately so it has its own lifecycle
# --------------------------------------------------------------------------- #
def tunnel_path() -> Path:
    return state_dir() / "tunnel.json"


def load_tunnel() -> dict:
    path = tunnel_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            return {}
    return {}


def save_tunnel(state: dict) -> None:
    tunnel_path().write_text(json.dumps(state, indent=2))


def clear_tunnel() -> None:
    path = tunnel_path()
    if path.exists():
        path.unlink()


def has_tunnel() -> bool:
    return tunnel_path().exists()
