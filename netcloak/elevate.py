"""Run netcloak's own privileged commands with an OS elevation prompt.

The GUI stays at normal-user level and calls run_elevated([...]) only for the
actions that truly need root/admin (changing a MAC, DNS, etc.). Each platform
gets its native prompt:

* Windows -> UAC dialog (Start-Process -Verb RunAs)
* macOS   -> password dialog (osascript "with administrator privileges")
* Linux   -> polkit dialog (pkexec)
"""
from __future__ import annotations

import platform
import shlex
import subprocess
import sys

from .privileges import is_admin

CREATE_NO_WINDOW = 0x08000000


def _self_cmd(args):
    """The command that re-invokes THIS program's CLI with `args`."""
    if getattr(sys, "frozen", False):
        # packaged binary: the exe itself dispatches to the CLI when given args
        return [sys.executable, *args]
    return [sys.executable, "-m", "netcloak", *args]


def run_elevated(args):
    """Run our CLI with `args` as admin/root. Blocks. Returns (ok, text)."""
    base = _self_cmd(args)
    if is_admin():
        return _plain(base)
    system = platform.system()
    if system == "Darwin":
        return _macos(base)
    if system == "Windows":
        return _windows(base)
    return _linux(base)


def _plain(base):
    p = subprocess.run(base, capture_output=True, text=True)
    return p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()


def _macos(base):
    shell_cmd = " ".join(shlex.quote(x) for x in base)
    applescript_arg = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "{applescript_arg}" with administrator privileges'
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if p.returncode != 0:
        msg = (p.stderr or "").strip()
        if "cancel" in msg.lower() or "-128" in msg:
            return False, "Cancelled at the password prompt."
        return False, msg or "Elevation failed."
    return True, (p.stdout or "").strip() or "Done."


def _linux(base):
    from .util import which

    if which("pkexec"):
        p = subprocess.run(["pkexec", *base], capture_output=True, text=True)
        if p.returncode == 126:
            return False, "Cancelled at the authentication prompt."
        return p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()
    return False, "Root required: install pkexec, or run from a terminal with sudo."


def _windows(base):
    exe = base[0].replace("'", "''")
    rest = base[1:]
    argpart = ""
    if rest:
        arglist = ",".join("'" + a.replace("'", "''") + "'" for a in rest)
        argpart = f" -ArgumentList {arglist}"
    ps = (
        f"try {{ $p = Start-Process -FilePath '{exe}'{argpart} -Verb RunAs -Wait "
        f"-PassThru -ErrorAction Stop; exit $p.ExitCode }} catch {{ exit 1223 }}"
    )
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    if p.returncode == 1223:
        return False, "Cancelled at the UAC prompt."
    return p.returncode == 0, "Done." if p.returncode == 0 else (p.stderr or "Elevation failed.")
