"""Shared helpers: command execution, MAC/hostname generation, output."""
from __future__ import annotations

import os
import random
import shutil
import signal
import string
import subprocess
import sys
from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# command execution
# --------------------------------------------------------------------------- #
def run(cmd, capture=True, shell=False, timeout=60):
    """Run a command. Returns (returncode, stdout, stderr).

    `cmd` is a list of args (or a string when shell=True). Never raises on a
    non-zero exit code or a missing binary -- callers inspect the return code
    so a single failing step never crashes the whole run.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            shell=shell,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def powershell(script, timeout=90):
    """Run a PowerShell script block (Windows). Returns (rc, stdout, stderr)."""
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


def spawn(cmd):
    """Start a detached background process (e.g. tor) and return its pid."""
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs).pid


def kill(pid):
    """Terminate a process started with spawn(). Best-effort."""
    try:
        if os.name == "nt":
            run(["taskkill", "/PID", str(pid), "/F", "/T"])
        else:
            os.kill(int(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError, ValueError):
        pass


def which(name):
    return shutil.which(name)


# --------------------------------------------------------------------------- #
# identity generation
# --------------------------------------------------------------------------- #
def random_mac(keep_oui: str | None = None) -> str:
    """Random, locally-administered, unicast MAC address.

    The first octet has the locally-administered bit set (0x02) and the
    multicast bit cleared -- this is exactly what the OS built-in Wi-Fi
    randomisation does. Pass keep_oui='aa:bb:cc' to preserve a real vendor
    prefix instead (blends in better, but is traceable to a vendor).
    """
    if keep_oui:
        octets = [int(x, 16) for x in keep_oui.replace("-", ":").split(":")[:3]]
    else:
        first = (random.randint(0x00, 0xFF) & 0xFE) | 0x02
        octets = [first, random.randint(0x00, 0xFF), random.randint(0x00, 0xFF)]
    octets += [random.randint(0x00, 0xFF) for _ in range(3)]
    return ":".join(f"{o:02x}" for o in octets)


def random_hostname() -> str:
    """A generic Windows-style name that blends into a typical network."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=7))
    return f"DESKTOP-{suffix}"


# --------------------------------------------------------------------------- #
# DNS providers
# --------------------------------------------------------------------------- #
DNS_PROVIDERS = {
    "cloudflare": {
        "v4": ["1.1.1.1", "1.0.0.1"],
        "v6": ["2606:4700:4700::1111", "2606:4700:4700::1001"],
        "doh": "https://cloudflare-dns.com/dns-query",
        "dot": "cloudflare-dns.com",
    },
    "quad9": {
        "v4": ["9.9.9.9", "149.112.112.112"],
        "v6": ["2620:fe::fe", "2620:fe::9"],
        "doh": "https://dns.quad9.net/dns-query",
        "dot": "dns.quad9.net",
    },
    "adguard": {
        "v4": ["94.140.14.14", "94.140.15.15"],
        "v6": ["2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff"],
        "doh": "https://dns.adguard-dns.com/dns-query",
        "dot": "dns.adguard-dns.com",
    },
}


# --------------------------------------------------------------------------- #
# terminal output
# --------------------------------------------------------------------------- #
class C:
    ok = "\033[92m"
    warn = "\033[93m"
    err = "\033[91m"
    dim = "\033[2m"
    bold = "\033[1m"
    cyan = "\033[96m"
    end = "\033[0m"


def _color(text, code):
    if sys.stdout.isatty():
        return f"{code}{text}{C.end}"
    return text


def info(msg):
    print(_color("  ·", C.cyan), msg)


def ok(msg):
    print(_color("  ✓", C.ok), msg)


def warn(msg):
    print(_color("  !", C.warn), msg)


def err(msg):
    print(_color("  ✗", C.err), msg)


def title(msg):
    print("\n" + _color(msg, C.bold))


def hr():
    print(_color("─" * 52, C.dim))
