"""Windows backend: PowerShell + registry (MAC via NetworkAddress key)."""
from __future__ import annotations

import json

from ..util import DNS_PROVIDERS, powershell
from .base import Backend, Interface, StepResult

CLASS_KEY = r"HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}"
DNSCLIENT_KEY = r"HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient"
DNSCACHE_KEY = r"HKLM:\SYSTEM\CurrentControlSet\Services\Dnscache\Parameters"


class WindowsBackend(Backend):
    name = "windows"

    # ------------------------------------------------------------------ #
    # discovery
    # ------------------------------------------------------------------ #
    def list_interfaces(self):
        script = (
            "Get-NetAdapter | Select-Object "
            "Name,MacAddress,InterfaceGuid,Status,InterfaceDescription "
            "| ConvertTo-Json -Compress"
        )
        _, out, _ = powershell(script)
        try:
            data = json.loads(out) if out else []
        except ValueError:
            data = []
        if isinstance(data, dict):
            data = [data]
        _, active, _ = powershell(
            "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
            "Sort-Object RouteMetric | Select-Object -First 1).InterfaceAlias"
        )
        res = []
        for a in data:
            desc = (a.get("InterfaceDescription") or "").lower()
            name = a.get("Name", "")
            kind = "wifi" if ("wireless" in desc or "wi-fi" in name.lower()) else "ethernet"
            mac = (a.get("MacAddress") or "").replace("-", ":").lower()
            res.append(Interface(name=name, mac=mac, kind=kind, active=name == active.strip()))
        return res

    def get_mac(self, iface):
        _, out, _ = powershell(f"(Get-NetAdapter -Name '{iface}').MacAddress")
        return out.replace("-", ":").lower()

    def get_hostname(self):
        return powershell("$env:COMPUTERNAME")[1]

    def get_dns(self):
        di = self.default_interface()
        if not di:
            return []
        _, out, _ = powershell(
            f"(Get-DnsClientServerAddress -InterfaceAlias '{di.name}' "
            "-AddressFamily IPv4).ServerAddresses -join ','"
        )
        return out.split(",") if out else []

    # ------------------------------------------------------------------ #
    # MAC (registry NetworkAddress + adapter restart)
    # ------------------------------------------------------------------ #
    def spoof_mac(self, iface, mac):
        old = self.get_mac(iface)
        macval = mac.replace(":", "").upper()
        script = f"""
$name='{iface}'
$guid=(Get-NetAdapter -Name $name).InterfaceGuid
$key=Get-ChildItem '{CLASS_KEY}' | Where-Object {{
  (Get-ItemProperty $_.PSPath -Name NetCfgInstanceId -EA SilentlyContinue).NetCfgInstanceId -eq $guid
}} | Select-Object -First 1
if(-not $key){{ Write-Output 'NOKEY'; exit }}
$prev=(Get-ItemProperty $key.PSPath -Name NetworkAddress -EA SilentlyContinue).NetworkAddress
Set-ItemProperty -Path $key.PSPath -Name NetworkAddress -Value '{macval}'
Restart-NetAdapter -Name $name -ErrorAction SilentlyContinue
Write-Output ('KEY=' + $key.PSPath)
Write-Output ('PREV=' + $prev)
"""
        _, out, e = powershell(script)
        backup = {"iface": iface, "regpath": None, "prev": None}
        for line in out.splitlines():
            if line.startswith("KEY="):
                backup["regpath"] = line[4:].strip()
            elif line.startswith("PREV="):
                backup["prev"] = line[5:].strip() or None
        if "NOKEY" in out:
            return StepResult("MAC address", "fail", "adapter registry key not found"), backup
        new = self.get_mac(iface)
        if new.replace(":", "").upper() == macval:
            return StepResult("MAC address", "ok", f"{iface}: {old} → {new}"), backup
        return (
            StepResult("MAC address", "fail", f"{iface}: driver rejected the change ({new})"),
            backup,
        )

    def restore_mac(self, backup):
        path, prev, iface = backup.get("regpath"), backup.get("prev"), backup.get("iface")
        if not path:
            return StepResult("MAC address", "fail", "no saved registry key")
        if prev:
            script = (
                f"Set-ItemProperty -Path '{path}' -Name NetworkAddress -Value '{prev}'; "
                f"Restart-NetAdapter -Name '{iface}' -EA SilentlyContinue"
            )
        else:
            script = (
                f"Remove-ItemProperty -Path '{path}' -Name NetworkAddress -EA SilentlyContinue; "
                f"Restart-NetAdapter -Name '{iface}' -EA SilentlyContinue"
            )
        powershell(script)
        return StepResult("MAC address", "ok", f"{iface} restored")

    # ------------------------------------------------------------------ #
    # hostname (needs reboot)
    # ------------------------------------------------------------------ #
    def set_hostname(self, name):
        old = self.get_hostname()
        safe = name[:15]
        rc, _, e = powershell(f"Rename-Computer -NewName '{safe}' -Force")
        status = "ok" if rc == 0 else "fail"
        msg = f"{old} → {safe} (reboot required to apply)" if rc == 0 else (e or "rename failed")
        return StepResult("Hostname", status, msg), {"hostname": old}

    def restore_hostname(self, backup):
        old = backup.get("hostname", "") if backup else ""
        if not old:
            return StepResult("Hostname", "fail", "no saved hostname")
        powershell(f"Rename-Computer -NewName '{old}' -Force")
        return StepResult("Hostname", "ok", f"→ {old} (reboot required)")

    # ------------------------------------------------------------------ #
    # broadcasts: LLMNR + mDNS (registry) + NetBIOS (per adapter)
    # ------------------------------------------------------------------ #
    def quiet_broadcasts(self):
        backup = {}
        _, llmnr, _ = powershell(
            f"(Get-ItemProperty '{DNSCLIENT_KEY}' -Name EnableMulticast -EA SilentlyContinue)"
            ".EnableMulticast"
        )
        backup["llmnr_prev"] = llmnr.strip() or None
        powershell(
            f"New-Item -Path '{DNSCLIENT_KEY}' -Force | Out-Null; "
            f"Set-ItemProperty -Path '{DNSCLIENT_KEY}' -Name EnableMulticast -Type DWord -Value 0"
        )
        _, mdns, _ = powershell(
            f"(Get-ItemProperty '{DNSCACHE_KEY}' -Name EnableMDNS -EA SilentlyContinue).EnableMDNS"
        )
        backup["mdns_prev"] = mdns.strip() or None
        powershell(
            f"Set-ItemProperty -Path '{DNSCACHE_KEY}' -Name EnableMDNS -Type DWord -Value 0"
        )
        powershell(
            "Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | "
            "ForEach-Object { $_.SetTcpipNetbios(2) } | Out-Null"
        )
        backup["netbios"] = True
        return StepResult("LAN broadcasts", "ok", "LLMNR + mDNS + NetBIOS disabled"), backup

    def restore_broadcasts(self, backup):
        if not backup:
            return StepResult("LAN broadcasts", "fail", "nothing to restore")
        if backup.get("llmnr_prev"):
            powershell(
                f"Set-ItemProperty -Path '{DNSCLIENT_KEY}' -Name EnableMulticast "
                f"-Type DWord -Value {backup['llmnr_prev']}"
            )
        else:
            powershell(
                f"Remove-ItemProperty -Path '{DNSCLIENT_KEY}' -Name EnableMulticast -EA SilentlyContinue"
            )
        if backup.get("mdns_prev"):
            powershell(
                f"Set-ItemProperty -Path '{DNSCACHE_KEY}' -Name EnableMDNS "
                f"-Type DWord -Value {backup['mdns_prev']}"
            )
        else:
            powershell(
                f"Remove-ItemProperty -Path '{DNSCACHE_KEY}' -Name EnableMDNS -EA SilentlyContinue"
            )
        if backup.get("netbios"):
            powershell(
                "Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | "
                "ForEach-Object { $_.SetTcpipNetbios(0) } | Out-Null"
            )
        return StepResult("LAN broadcasts", "ok", "restored")

    # ------------------------------------------------------------------ #
    # DNS (Windows 11 DoH)
    # ------------------------------------------------------------------ #
    def private_dns(self, provider):
        p = DNS_PROVIDERS[provider]
        di = self.default_interface()
        if not di:
            return StepResult("Encrypted DNS", "fail", "no active interface"), None
        iface = di.name
        _, cur, _ = powershell(
            f"(Get-DnsClientServerAddress -InterfaceAlias '{iface}' "
            "-AddressFamily IPv4).ServerAddresses -join ','"
        )
        backup = {"iface": iface, "dns": cur.strip(), "doh_servers": p["v4"]}
        for s in p["v4"]:
            powershell(
                f"netsh dns add encryption server={s} dohtemplate={p['doh']} "
                "autoupgrade=yes udpfallback=no"
            )
        powershell(
            f"Set-DnsClientServerAddress -InterfaceAlias '{iface}' "
            f"-ServerAddresses {','.join(p['v4'])}"
        )
        return StepResult("Encrypted DNS", "ok", f"{iface}: DoH via {provider}"), backup

    def restore_dns(self, backup):
        if not backup:
            return StepResult("Encrypted DNS", "fail", "nothing to restore")
        iface = backup.get("iface")
        if backup.get("dns"):
            powershell(
                f"Set-DnsClientServerAddress -InterfaceAlias '{iface}' "
                f"-ServerAddresses {backup['dns']}"
            )
        else:
            powershell(f"Set-DnsClientServerAddress -InterfaceAlias '{iface}' -ResetServerAddresses")
        for s in backup.get("doh_servers", []):  # undo the DoH template registrations
            powershell(f"netsh dns delete encryption server={s}")
        return StepResult("Encrypted DNS", "ok", f"{iface} DNS restored")
