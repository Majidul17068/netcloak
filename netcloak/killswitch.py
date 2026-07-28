"""Kill switch: block traffic that isn't going through the VPN, so nothing
leaks over your real connection if the tunnel drops.

* macOS  -> a `pf` ruleset that permits only loopback, the tunnel interface,
            the VPN endpoint, and the local LAN; everything else outbound is
            dropped (IPv6 fully blocked too, closing v6 leaks).
* Linux  -> wg-quick already installs a route-based kill switch for
            full-tunnel (AllowedIPs 0.0.0.0/0) configs — reported, no-op.
* Windows-> the WireGuard service blocks untunneled traffic for full-tunnel
            configs — reported, no-op.

Everything is reversible: disable() restores the OS default firewall.
Recovery if something goes wrong on macOS:
    sudo pfctl -f /etc/pf.conf        # restore default rules
"""
from __future__ import annotations

import platform
import re
import socket

from .backends.base import StepResult
from .state import state_dir
from .util import run

PF_CONF = state_dir() / "killswitch.pf.conf"


def _endpoint(config_path):
    """Return (ip, port) of the WireGuard Endpoint, resolving a hostname."""
    try:
        with open(config_path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return None, None
    m = re.search(r"(?im)^\s*Endpoint\s*=\s*(.+?):(\d+)\s*$", text)
    if not m:
        return None, None
    host, port = m.group(1).strip(), m.group(2)
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        ip = host
    return ip, port


def enable(config):
    system = platform.system()
    if system == "Darwin":
        return _macos_enable(config)
    if system == "Linux":
        return (
            StepResult("Kill switch", "ok", "provided by wg-quick (full-tunnel route guard)"),
            {"os": "Linux"},
        )
    if system == "Windows":
        return (
            StepResult("Kill switch", "ok", "provided by the WireGuard service (blocks untunneled)"),
            {"os": "Windows"},
        )
    return StepResult("Kill switch", "skip", "not supported on this platform"), None


def disable(backup):
    if not backup:
        return StepResult("Kill switch", "skip", "nothing to restore")
    if backup.get("os") == "Darwin":
        run(["pfctl", "-f", "/etc/pf.conf"])
        if not backup.get("pf_was_enabled"):
            run(["pfctl", "-d"])
        return StepResult("Kill switch", "ok", "firewall restored")
    return StepResult("Kill switch", "ok", "released")


# --------------------------------------------------------------------------- #
# macOS pf implementation
# --------------------------------------------------------------------------- #
def _macos_enable(config):
    ip, port = _endpoint(config)
    if not ip:
        return StepResult("Kill switch", "fail", "couldn't read VPN endpoint from config"), None

    _, info, _ = run(["pfctl", "-s", "info"])
    was_enabled = "Status: Enabled" in info

    utun_passes = "\n".join(f"pass out quick on utun{i}" for i in range(12))
    rules = f"""set block-policy drop
set skip on lo0
# reach the VPN server so the tunnel can connect / reconnect
pass out quick inet proto udp to {ip} port {port}
pass out quick inet proto tcp to {ip} port {port}
# allow the encrypted tunnel interfaces
{utun_passes}
# keep the LAN working (router, DHCP) so we can reconnect
pass out quick inet to 192.168.0.0/16
pass out quick inet to 10.0.0.0/8
pass out quick inet to 172.16.0.0/12
pass out quick inet proto udp to any port 67
pass in quick inet proto udp from any port 67
# block everything else — this is the kill switch (v6 leaks blocked too)
block drop out inet all
block drop out inet6 all
"""
    PF_CONF.write_text(rules)
    rc, out, err = run(["pfctl", "-f", str(PF_CONF)])
    if rc != 0:
        run(["pfctl", "-f", "/etc/pf.conf"])  # fail safe — never leave partial rules
        return StepResult("Kill switch", "fail", (err or out or "pfctl load failed")[:200]), None
    run(["pfctl", "-e"])  # enable pf (harmless if already on)
    return (
        StepResult("Kill switch", "ok", "on — traffic blocked unless it goes through the VPN"),
        {"os": "Darwin", "pf_was_enabled": was_enabled},
    )
