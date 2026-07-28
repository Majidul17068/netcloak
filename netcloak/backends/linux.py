"""Linux backend: iproute2 + systemd-resolved + NetworkManager + avahi."""
from __future__ import annotations

from pathlib import Path

from ..util import DNS_PROVIDERS, run, which
from .base import Backend, Interface, StepResult

RESOLVED_DIR = Path("/etc/systemd/resolved.conf.d")
DNS_DROPIN = RESOLVED_DIR / "00-netcloak-dns.conf"
BCAST_DROPIN = RESOLVED_DIR / "00-netcloak-broadcast.conf"
NM_DROPIN = Path("/etc/NetworkManager/conf.d/00-netcloak.conf")


class LinuxBackend(Backend):
    name = "linux"

    # ------------------------------------------------------------------ #
    # discovery
    # ------------------------------------------------------------------ #
    def list_interfaces(self):
        _, out, _ = run(["ip", "-o", "link", "show"])
        active = self._default_route_ifaces()
        ifaces = []
        for line in out.splitlines():
            parts = line.split(": ", 2)
            if len(parts) < 3:
                continue
            name = parts[1].split("@")[0]
            if name == "lo":
                continue
            mac = ""
            if "link/ether" in parts[2]:
                mac = parts[2].split("link/ether", 1)[1].split()[0]
            ifaces.append(
                Interface(name=name, mac=mac, kind=self._kind(name), active=name in active)
            )
        return ifaces

    def _default_route_ifaces(self):
        _, out, _ = run(["ip", "route", "show", "default"])
        res = set()
        for line in out.splitlines():
            if " dev " in line:
                res.add(line.split(" dev ", 1)[1].split()[0])
        return res

    def _kind(self, name):
        return "wifi" if Path(f"/sys/class/net/{name}/wireless").exists() else "ethernet"

    def _uses_resolved(self):
        if Path("/run/systemd/resolve").exists():
            return True
        return run(["systemctl", "is-active", "systemd-resolved"])[1] == "active"

    def get_mac(self, iface):
        p = Path(f"/sys/class/net/{iface}/address")
        return p.read_text().strip() if p.exists() else ""

    def get_hostname(self):
        return run(["hostname"])[1]

    def get_dns(self):
        rc, out, _ = run(["resolvectl", "dns"])
        if rc == 0 and out:
            servers = []
            for line in out.splitlines():
                if ":" in line:
                    servers += line.split(":", 1)[1].split()
            if servers:
                return servers
        try:
            txt = Path("/etc/resolv.conf").read_text()
            return [l.split()[1] for l in txt.splitlines() if l.startswith("nameserver")]
        except OSError:
            return []

    # ------------------------------------------------------------------ #
    # MAC
    # ------------------------------------------------------------------ #
    def spoof_mac(self, iface, mac):
        old = self.get_mac(iface)
        backup = {"iface": iface, "mac": old}
        run(["ip", "link", "set", "dev", iface, "down"])
        _, _, e = run(["ip", "link", "set", "dev", iface, "address", mac])
        run(["ip", "link", "set", "dev", iface, "up"])
        new = self.get_mac(iface)
        if new.lower() == mac.lower():
            return StepResult("MAC address", "ok", f"{iface}: {old} → {new}"), backup
        return (
            StepResult("MAC address", "fail", f"{iface}: driver refused ({e or new})"),
            backup,
        )

    def restore_mac(self, backup):
        if not backup or not backup.get("mac"):
            return StepResult("MAC address", "fail", "no saved MAC")
        iface, mac = backup["iface"], backup["mac"]
        run(["ip", "link", "set", "dev", iface, "down"])
        run(["ip", "link", "set", "dev", iface, "address", mac])
        run(["ip", "link", "set", "dev", iface, "up"])
        return StepResult("MAC address", "ok", f"{iface} → {mac}")

    # ------------------------------------------------------------------ #
    # hostname
    # ------------------------------------------------------------------ #
    def set_hostname(self, name):
        old = self.get_hostname()
        if which("hostnamectl"):
            run(["hostnamectl", "set-hostname", name])
            run(["hostnamectl", "set-hostname", "--transient", name])
        else:
            run(["hostname", name])
        self._nm_send_hostname(False)
        return StepResult("Hostname", "ok", f"{old} → {name} (DHCP hostname suppressed)"), {
            "hostname": old
        }

    def restore_hostname(self, backup):
        if not backup:
            return StepResult("Hostname", "fail", "no saved hostname")
        name = backup.get("hostname", "")
        if not name:
            # never clobber with an empty hostname — just undo the DHCP change
            self._nm_send_hostname(True)
            return StepResult("Hostname", "skip", "no original hostname recorded")
        if which("hostnamectl"):
            run(["hostnamectl", "set-hostname", name])
            run(["hostnamectl", "set-hostname", "--transient", name])
        else:
            run(["hostname", name])
        self._nm_send_hostname(True)
        return StepResult("Hostname", "ok", f"restored to {name}")

    def _nm_send_hostname(self, send):
        if not Path("/etc/NetworkManager").exists():
            return
        if send:
            if NM_DROPIN.exists():
                NM_DROPIN.unlink()
        else:
            NM_DROPIN.write_text(
                "[connection]\n"
                "ipv4.dhcp-send-hostname=false\n"
                "ipv6.dhcp-send-hostname=false\n"
            )
        run(["systemctl", "reload-or-restart", "NetworkManager"])

    # ------------------------------------------------------------------ #
    # broadcasts
    # ------------------------------------------------------------------ #
    def quiet_broadcasts(self):
        notes, backup = [], {}
        if self._uses_resolved():
            RESOLVED_DIR.mkdir(parents=True, exist_ok=True)
            BCAST_DROPIN.write_text("[Resolve]\nLLMNR=no\nMulticastDNS=no\n")
            backup["resolved_file"] = str(BCAST_DROPIN)
            run(["systemctl", "restart", "systemd-resolved"])
            notes.append("LLMNR + mDNS off")
        _, active, _ = run(["systemctl", "is-active", "avahi-daemon"])
        backup["avahi_was_active"] = active == "active"
        if active == "active":
            run(["systemctl", "stop", "avahi-daemon.socket"])
            run(["systemctl", "stop", "avahi-daemon"])
            notes.append("avahi stopped")
        if not notes:
            return StepResult("LAN broadcasts", "skip", "no systemd-resolved/avahi found"), backup
        return StepResult("LAN broadcasts", "ok", "; ".join(notes)), backup

    def restore_broadcasts(self, backup):
        if not backup:
            return StepResult("LAN broadcasts", "fail", "nothing to restore")
        f = backup.get("resolved_file")
        if f and Path(f).exists():
            Path(f).unlink()
            run(["systemctl", "restart", "systemd-resolved"])
        if backup.get("avahi_was_active"):
            run(["systemctl", "start", "avahi-daemon"])
        return StepResult("LAN broadcasts", "ok", "restored")

    # ------------------------------------------------------------------ #
    # DNS
    # ------------------------------------------------------------------ #
    def private_dns(self, provider):
        p = DNS_PROVIDERS[provider]
        if self._uses_resolved():
            dns_line = " ".join(f"{ip}#{p['dot']}" for ip in p["v4"] + p["v6"])
            RESOLVED_DIR.mkdir(parents=True, exist_ok=True)
            DNS_DROPIN.write_text(
                f"[Resolve]\nDNS={dns_line}\nDNSOverTLS=yes\nDomains=~.\n"
            )
            run(["systemctl", "restart", "systemd-resolved"])
            return (
                StepResult("Encrypted DNS", "ok", f"DNS-over-TLS via {provider}"),
                {"mode": "resolved", "file": str(DNS_DROPIN)},
            )
        try:
            orig = Path("/etc/resolv.conf").read_text()
        except OSError:
            orig = ""
        Path("/etc/resolv.conf").write_text(
            "\n".join(f"nameserver {ip}" for ip in p["v4"]) + "\n"
        )
        return (
            StepResult(
                "Encrypted DNS",
                "skip",
                f"{provider} set but PLAINTEXT (no systemd-resolved for DoT)",
            ),
            {"mode": "resolv", "orig": orig},
        )

    def restore_dns(self, backup):
        if not backup:
            return StepResult("Encrypted DNS", "fail", "nothing to restore")
        if backup.get("mode") == "resolved":
            f = Path(backup["file"])
            if f.exists():
                f.unlink()
            run(["systemctl", "restart", "systemd-resolved"])
            return StepResult("Encrypted DNS", "ok", "DoT config removed")
        Path("/etc/resolv.conf").write_text(backup.get("orig", ""))
        return StepResult("Encrypted DNS", "ok", "resolv.conf restored")
