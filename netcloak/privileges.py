"""Admin / root privilege detection and guidance."""
from __future__ import annotations

import os
import sys


def is_admin() -> bool:
    if os.name == "nt":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def elevation_hint() -> str:
    if os.name == "nt":
        return "Right-click your terminal and choose 'Run as administrator'."
    return f"Re-run with sudo, e.g.  sudo {os.path.basename(sys.executable)} -m netcloak ..."
