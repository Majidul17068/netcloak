"""Auto-install the runtimes the tunnel layer needs (Tor, WireGuard tools).

Called from inside the elevated `tunnel up`, so we're already root/admin on
Linux/Windows. On macOS, Homebrew refuses to run as root, so we run it as the
logged-in console user via `sudo -u`.

Only Tor and WireGuard need installing — AdGuard/Cloudflare/Quad9 are just DNS
providers (server addresses), nothing to install.
"""
from __future__ import annotations

import os
import platform

from .util import powershell, run, which

BREW_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")

# runtime that proves a tool is present
_CHECK = {"tor": "tor", "wireguard": "wg-quick"}
# package name per manager
_PKG = {
    "tor": {"brew": "tor", "apt": "tor", "dnf": "tor", "pacman": "tor", "zypper": "tor"},
    "wireguard": {
        "brew": "wireguard-tools",
        "apt": "wireguard-tools",
        "dnf": "wireguard-tools",
        "pacman": "wireguard-tools",
        "zypper": "wireguard-tools",
    },
}


def tool_path(name):
    """Resolve an executable, including Homebrew dirs that root's PATH omits."""
    found = which(name)
    if found:
        return found
    for d in BREW_DIRS:
        cand = os.path.join(d, name)
        if os.path.exists(cand):
            return cand
    return name


def _installed(tool):
    if tool == "wireguard" and platform.system() == "Windows":
        return which("wireguard") is not None or os.path.exists(
            r"C:\Program Files\WireGuard\wireguard.exe"
        )
    return tool_path(_CHECK[tool]) != _CHECK[tool]


def ensure(tool):
    """Make `tool` ('tor'|'wireguard') available. Returns (ok, message)."""
    if _installed(tool):
        return True, f"{tool} already installed"
    system = platform.system()
    if system == "Darwin":
        return _install_mac(tool)
    if system == "Linux":
        return _install_linux(tool)
    if system == "Windows":
        return _install_windows(tool)
    return False, f"cannot auto-install {tool} on {system}"


# --------------------------------------------------------------------------- #
# macOS — Homebrew (run as the console user, never root)
# --------------------------------------------------------------------------- #
def _mac_console_user():
    rc, out, _ = run(["stat", "-f", "%Su", "/dev/console"])
    user = out.strip() if rc == 0 else ""
    if user and user != "root":
        return user
    return os.environ.get("SUDO_USER", "")


def _brew_bin():
    for d in BREW_DIRS:
        cand = os.path.join(d, "brew")
        if os.path.exists(cand):
            return cand
    return which("brew")


def _install_mac(tool):
    pkg = _PKG[tool]["brew"]
    brew = _brew_bin()
    if not brew:
        return False, f"Homebrew not installed — install from https://brew.sh, then: brew install {pkg}"
    user = _mac_console_user()
    cmd = ["sudo", "-u", user, brew, "install", pkg] if (os.geteuid() == 0 and user) else [brew, "install", pkg]
    rc, out, err = run(cmd, timeout=600)
    if _installed(tool):
        return True, f"installed {pkg} via Homebrew"
    return False, (err or out or "brew install failed")[:300]


# --------------------------------------------------------------------------- #
# Linux — native package manager (already root here)
# --------------------------------------------------------------------------- #
def _linux_installer():
    if which("apt-get"):
        return "apt", ["apt-get", "install", "-y"]
    if which("dnf"):
        return "dnf", ["dnf", "install", "-y"]
    if which("pacman"):
        return "pacman", ["pacman", "-S", "--noconfirm"]
    if which("zypper"):
        return "zypper", ["zypper", "--non-interactive", "install"]
    return None, None


def _install_linux(tool):
    mgr, install = _linux_installer()
    if not mgr:
        return False, f"no supported package manager found — install {_PKG[tool]['apt']} manually"
    if mgr == "apt":
        run(["apt-get", "update"], timeout=180)
    rc, out, err = run(install + [_PKG[tool][mgr]], timeout=600)
    if _installed(tool):
        return True, f"installed {_PKG[tool][mgr]} via {mgr}"
    return False, (err or out or "install failed")[:300]


# --------------------------------------------------------------------------- #
# Windows — winget (WireGuard only; no reliable Tor daemon package)
# --------------------------------------------------------------------------- #
def _install_windows(tool):
    if tool == "wireguard":
        if not which("winget"):
            return False, "winget unavailable — install WireGuard from wireguard.com"
        rc, out, err = powershell(
            "winget install --id WireGuard.WireGuard -e "
            "--accept-source-agreements --accept-package-agreements",
            timeout=600,
        )
        if _installed(tool):
            return True, "installed WireGuard via winget"
        return False, (err or out or "winget install failed")[:300]
    return False, (
        "automatic Tor install isn't available on Windows — install the Tor "
        "Expert Bundle from torproject.org, or use WireGuard instead"
    )
