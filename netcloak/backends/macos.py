"""macOS backend: ifconfig + networksetup + scutil.

Honest caveats baked in: on Apple Silicon / T2 Macs the Wi-Fi driver often
reverts a spoofed MAC, and mDNSResponder can't be safely disabled, so those
steps report `skip`/`fail` rather than pretending to succeed.
"""
from __future__ import annotations

import re
import time
import uuid

from ..state import state_dir
from ..util import DNS_PROVIDERS, run
from .base import Backend, Interface, StepResult


class MacBackend(Backend):
    name = "macos"

    # ------------------------------------------------------------------ #
    # discovery
    # ------------------------------------------------------------------ #
    def _hardware_ports(self):
        _, out, _ = run(["networksetup", "-listallhardwareports"])
        ports, cur = [], {}
        for line in out.splitlines():
            if line.startswith("Hardware Port:"):
                cur = {"port": line.split(":", 1)[1].strip()}
            elif line.startswith("Device:"):
                cur["device"] = line.split(":", 1)[1].strip()
            elif line.startswith("Ethernet Address:"):
                cur["mac"] = line.split(":", 1)[1].strip()
                ports.append(cur)
                cur = {}
        return ports

    def _active_device(self):
        _, out, _ = run(["route", "-n", "get", "default"])
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("interface:"):
                return line.split(":", 1)[1].strip()
        return None

    def list_interfaces(self):
        active = self._active_device()
        res = []
        for hp in self._hardware_ports():
            dev = hp.get("device")
            if not dev:
                continue
            port = hp.get("port", "")
            kind = "wifi" if ("Wi-Fi" in port or "AirPort" in port) else "ethernet"
            res.append(
                Interface(name=dev, mac=hp.get("mac", ""), kind=kind, active=dev == active)
            )
        return res

    def _service_for_device(self, device):
        _, out, _ = run(["networksetup", "-listnetworkserviceorder"])
        svc = None
        for line in out.splitlines():
            m = re.match(r"\(\d+\)\s+(.*)", line)
            if m:
                svc = m.group(1).strip()
            elif "Device:" in line and f"Device: {device})" in line and svc:
                return svc
        return None

    def get_mac(self, iface):
        _, out, _ = run(["ifconfig", iface])
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("ether "):
                return line.split()[1]
        return ""

    def get_hostname(self):
        return run(["scutil", "--get", "ComputerName"])[1]

    def get_dns(self):
        _, out, _ = run(["scutil", "--dns"])
        seen, res = set(), []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("nameserver["):
                ip = line.split(":", 1)[1].strip()
                if ip not in seen:
                    seen.add(ip)
                    res.append(ip)
        return res

    # ------------------------------------------------------------------ #
    # MAC
    # ------------------------------------------------------------------ #
    def spoof_mac(self, iface, mac):
        old = self.get_mac(iface)
        backup = {"iface": iface, "mac": old}
        is_wifi = any(i.name == iface and i.kind == "wifi" for i in self.list_interfaces())
        if is_wifi:
            run(["networksetup", "-setairportpower", iface, "off"])
            time.sleep(2)
        _, _, e = run(["ifconfig", iface, "ether", mac])
        if is_wifi:
            run(["networksetup", "-setairportpower", iface, "on"])
            time.sleep(3)
        new = self.get_mac(iface)
        if new.lower() == mac.lower():
            return StepResult("MAC address", "ok", f"{iface}: {old} → {new}"), backup
        return (
            StepResult(
                "MAC address",
                "fail",
                f"{iface}: macOS kept {new} (Apple Silicon/T2 Wi-Fi commonly blocks this)",
            ),
            backup,
        )

    def restore_mac(self, backup):
        if not backup or not backup.get("mac"):
            return StepResult("MAC address", "fail", "no saved MAC")
        iface, mac = backup["iface"], backup["mac"]
        run(["ifconfig", iface, "ether", mac])
        return StepResult("MAC address", "ok", f"{iface} → {mac} (a reboot also restores it)")

    # ------------------------------------------------------------------ #
    # hostname
    # ------------------------------------------------------------------ #
    def set_hostname(self, name):
        backup = {}
        for key in ("ComputerName", "HostName", "LocalHostname"):
            rc, out, _ = run(["scutil", "--get", key])
            backup[key] = out if rc == 0 else ""
        safe = re.sub(r"[^A-Za-z0-9-]", "-", name)
        run(["scutil", "--set", "ComputerName", name])
        run(["scutil", "--set", "HostName", safe])
        run(["scutil", "--set", "LocalHostname", safe])
        return StepResult("Hostname", "ok", f"{backup.get('ComputerName', '?')} → {name}"), backup

    def restore_hostname(self, backup):
        if not backup:
            return StepResult("Hostname", "fail", "no saved hostname")
        for key in ("ComputerName", "HostName", "LocalHostname"):
            val = backup.get(key, "")
            if val:
                run(["scutil", "--set", key, val])
        return StepResult("Hostname", "ok", "restored")

    # ------------------------------------------------------------------ #
    # broadcasts
    # ------------------------------------------------------------------ #
    def quiet_broadcasts(self):
        # mDNSResponder is a core macOS service that also drives normal DNS;
        # disabling it breaks AirDrop/printing/name resolution, so we don't.
        return (
            StepResult(
                "LAN broadcasts",
                "skip",
                "macOS runs mDNS system-wide; disabling it breaks core features — left as-is",
            ),
            None,
        )

    # ------------------------------------------------------------------ #
    # DNS
    # ------------------------------------------------------------------ #
    def private_dns(self, provider):
        p = DNS_PROVIDERS[provider]
        dev = self._active_device()
        if not dev:
            di = self.default_interface()
            dev = di.name if di else None
        svc = self._service_for_device(dev) if dev else None
        if not svc:
            return StepResult("Encrypted DNS", "fail", "could not map interface to a service"), None
        _, cur, _ = run(["networksetup", "-getdnsservers", svc])
        backup = {
            "service": svc,
            "dns": [] if "aren't any" in cur.lower() else cur.split(),
        }
        run(["networksetup", "-setdnsservers", svc] + p["v4"] + p["v6"])
        profile = self._write_doh_profile(provider, p)
        return (
            StepResult(
                "Encrypted DNS",
                "ok",
                f"{svc} → {provider}. For true DoH, install profile: {profile}",
            ),
            backup,
        )

    def restore_dns(self, backup):
        if not backup:
            return StepResult("Encrypted DNS", "fail", "nothing to restore")
        svc = backup.get("service")
        dns = backup.get("dns") or ["empty"]
        run(["networksetup", "-setdnsservers", svc] + dns)
        return StepResult("Encrypted DNS", "ok", f"{svc} DNS restored")

    def _write_doh_profile(self, provider, p):
        puid, cuid = str(uuid.uuid4()).upper(), str(uuid.uuid4()).upper()
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>PayloadContent</key><array><dict>
    <key>DNSSettings</key><dict>
      <key>DNSProtocol</key><string>HTTPS</string>
      <key>ServerURL</key><string>{p['doh']}</string>
    </dict>
    <key>PayloadType</key><string>com.apple.dnsSettings.managed</string>
    <key>PayloadIdentifier</key><string>com.netcloak.doh.{provider}</string>
    <key>PayloadUUID</key><string>{puid}</string>
    <key>PayloadVersion</key><integer>1</integer>
    <key>PayloadDisplayName</key><string>netcloak Encrypted DNS ({provider})</string>
  </dict></array>
  <key>PayloadDisplayName</key><string>netcloak Encrypted DNS ({provider})</string>
  <key>PayloadIdentifier</key><string>com.netcloak.{cuid}</string>
  <key>PayloadType</key><string>Configuration</string>
  <key>PayloadUUID</key><string>{cuid}</string>
  <key>PayloadVersion</key><integer>1</integer>
</dict></plist>
"""
        path = state_dir() / f"netcloak-doh-{provider}.mobileconfig"
        path.write_text(plist)
        return str(path)
