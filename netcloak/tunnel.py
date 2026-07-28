"""Traffic tunnelling: hide *where* your browsing goes, not just who you are.

Two backends:

* WireGuard -- bring an existing .conf up/down (fast, needs a provider/server).
* Tor       -- launch a local Tor daemon exposing SOCKS5 on 127.0.0.1:9050 and
               point the system proxy at it (free, slower).

Both are fully reversible via the tunnel state file.
"""
from __future__ import annotations

import os
import platform

from .backends import get_backend
from .backends.base import StepResult
from .deps import ensure, tool_path
from .util import kill, powershell, run, spawn, which
from .state import state_dir

SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 9050
WININET = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"


# --------------------------------------------------------------------------- #
# WireGuard
# --------------------------------------------------------------------------- #
def _wireguard_exe():
    exe = which("wireguard")
    if exe:
        return exe
    default = r"C:\Program Files\WireGuard\wireguard.exe"
    return default if os.path.isfile(default) else None


def wireguard_up(config):
    system = platform.system()
    cfg = os.path.abspath(os.path.expanduser(config))
    if not os.path.isfile(cfg):
        return StepResult("WireGuard", "fail", f"config not found: {cfg}"), None

    # accept any provider's config, but confirm it's actually a WireGuard one
    try:
        with open(cfg, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError as exc:
        return StepResult("WireGuard", "fail", f"can't read config: {exc}"), None
    if "[Interface]" not in text or "[Peer]" not in text:
        return (
            StepResult(
                "WireGuard",
                "fail",
                "not a WireGuard config (no [Interface]/[Peer]) — pick the "
                "'WireGuard configuration' .conf, not an OpenVPN/other file",
            ),
            None,
        )

    ok, msg = ensure("wireguard")
    if not ok:
        return StepResult("WireGuard", "fail", msg), None

    if system in ("Linux", "Darwin"):
        if system == "Darwin":  # let wg-quick find Homebrew's wireguard-go under root's PATH
            os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
        else:  # elevated PATH can be minimal — make sure wg-quick/resolvconf resolve
            os.environ["PATH"] = os.environ.get("PATH", "") + ":/usr/bin:/usr/sbin:/bin:/sbin"
        rc, out, e = run([tool_path("wg-quick"), "up", cfg], timeout=60)
        if rc != 0:
            detail = (e or out or "wg-quick failed").strip()
            if "resolvconf" in detail.lower():
                detail += " — install 'openresolv' so wg-quick can set the VPN's DNS"
            return StepResult("WireGuard", "fail", detail[:300]), None
        return (
            StepResult("WireGuard", "ok", f"up ({os.path.basename(cfg)}) — all traffic tunnelled"),
            {"kind": "wireguard", "system": system, "config": cfg},
        )

    if system == "Windows":
        exe = _wireguard_exe()
        if not exe:
            return StepResult("WireGuard", "fail", "WireGuard not installed (wireguard.com)"), None
        rc, out, e = run([exe, "/installtunnelservice", cfg], timeout=45)
        if rc != 0:
            return StepResult("WireGuard", "fail", e or out or "install failed"), None
        name = os.path.splitext(os.path.basename(cfg))[0]
        return (
            StepResult("WireGuard", "ok", f"tunnel service '{name}' installed"),
            {"kind": "wireguard", "system": system, "config": cfg, "name": name},
        )

    return StepResult("WireGuard", "fail", f"unsupported platform: {system}"), None


def wireguard_down(state):
    system = state.get("system") or platform.system()
    if system in ("Linux", "Darwin"):
        if system == "Darwin":
            os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
        else:
            os.environ["PATH"] = os.environ.get("PATH", "") + ":/usr/bin:/usr/sbin:/bin:/sbin"
        rc, out, e = run([tool_path("wg-quick"), "down", state["config"]], timeout=60)
        return StepResult("WireGuard", "ok" if rc == 0 else "fail", "down" if rc == 0 else (e or out))
    if system == "Windows":
        exe = _wireguard_exe()
        if exe:
            run([exe, "/uninstalltunnelservice", state.get("name", "")], timeout=45)
        return StepResult("WireGuard", "ok", "tunnel service removed")
    return StepResult("WireGuard", "fail", "nothing to do")


# --------------------------------------------------------------------------- #
# Tor
# --------------------------------------------------------------------------- #
def tor_up():
    ok, msg = ensure("tor")
    if not ok:
        return StepResult("Tor", "fail", msg), None

    data = state_dir() / "tor-data"
    data.mkdir(parents=True, exist_ok=True)
    torrc = state_dir() / "torrc"
    torrc.write_text(
        f"SocksPort {SOCKS_PORT}\n"
        f"DNSPort 9053\n"
        f"AutomapHostsOnResolve 1\n"
        f"DataDirectory {data}\n"
    )
    pid = spawn([tool_path("tor"), "-f", str(torrc)])
    proxy = _set_socks_proxy()
    return (
        StepResult(
            "Tor",
            "ok",
            f"started (pid {pid}); SOCKS5 {SOCKS_HOST}:{SOCKS_PORT}, bootstrapping ~30s",
        ),
        {"kind": "tor", "system": platform.system(), "pid": pid, "proxy": proxy},
    )


def tor_down(state):
    if state.get("pid"):
        kill(state["pid"])
    _unset_socks_proxy(state.get("proxy"))
    return StepResult("Tor", "ok", "stopped; system proxy cleared")


# --------------------------------------------------------------------------- #
# system SOCKS proxy plumbing (used by Tor)
# --------------------------------------------------------------------------- #
def _set_socks_proxy():
    system = platform.system()
    if system == "Darwin":
        be = get_backend()
        dev = be._active_device()
        svc = be._service_for_device(dev) if dev else None
        if not svc:
            return {"system": system, "svc": None}
        _, cur, _ = run(["networksetup", "-getsocksfirewallproxy", svc])
        run(["networksetup", "-setsocksfirewallproxy", svc, SOCKS_HOST, str(SOCKS_PORT)])
        run(["networksetup", "-setsocksfirewallproxystate", svc, "on"])
        return {"system": system, "svc": svc, "prev_on": "Enabled: Yes" in cur}

    if system == "Windows":
        _, prev_srv, _ = powershell(f"(Get-ItemProperty '{WININET}' -Name ProxyServer -EA SilentlyContinue).ProxyServer")
        _, prev_en, _ = powershell(f"(Get-ItemProperty '{WININET}' -Name ProxyEnable -EA SilentlyContinue).ProxyEnable")
        powershell(
            f"Set-ItemProperty '{WININET}' -Name ProxyServer -Value 'socks={SOCKS_HOST}:{SOCKS_PORT}'; "
            f"Set-ItemProperty '{WININET}' -Name ProxyEnable -Value 1"
        )
        return {"system": system, "prev_server": prev_srv.strip(), "prev_enable": prev_en.strip()}

    if system == "Linux":
        if which("gsettings"):
            _, mode, _ = run(["gsettings", "get", "org.gnome.system.proxy", "mode"])
            run(["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"])
            run(["gsettings", "set", "org.gnome.system.proxy.socks", "host", SOCKS_HOST])
            run(["gsettings", "set", "org.gnome.system.proxy.socks", "port", str(SOCKS_PORT)])
            return {"system": system, "prev_mode": mode.strip().strip("'")}
        return {"system": system, "note": "set SOCKS 127.0.0.1:9050 manually / in your browser"}

    return {"system": system}


def _unset_socks_proxy(backup):
    if not backup:
        return
    system = backup.get("system")
    if system == "Darwin" and backup.get("svc"):
        run(["networksetup", "-setsocksfirewallproxystate", backup["svc"], "off"])
    elif system == "Windows":
        if backup.get("prev_server"):
            powershell(f"Set-ItemProperty '{WININET}' -Name ProxyServer -Value '{backup['prev_server']}'")
        powershell(f"Set-ItemProperty '{WININET}' -Name ProxyEnable -Value {backup.get('prev_enable') or 0}")
    elif system == "Linux" and which("gsettings"):
        run(["gsettings", "set", "org.gnome.system.proxy", "mode", backup.get("prev_mode") or "none"])
