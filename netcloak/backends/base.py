"""Backend interface shared by every platform."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Interface:
    name: str
    mac: str = ""
    kind: str = "unknown"  # wifi | ethernet | unknown
    active: bool = False


@dataclass
class StepResult:
    name: str
    status: str = "ok"  # ok | fail | skip
    message: str = ""


# Each action returns (StepResult, backup). `backup` is a JSON-serialisable
# dict stored in the state file and handed back verbatim to the matching
# restore_* method by `off`. A backup of None means "nothing to undo".
class Backend:
    name = "generic"

    # ------------------------------------------------------------------ #
    # discovery
    # ------------------------------------------------------------------ #
    def list_interfaces(self) -> list[Interface]:
        raise NotImplementedError

    def default_interface(self):
        ifaces = self.list_interfaces()
        for i in ifaces:
            if i.active:
                return i
        skip = ("lo", "utun", "awdl", "llw", "bridge", "gif", "stf", "ap")
        real = [i for i in ifaces if i.mac and not i.name.startswith(skip)]
        if real:
            return real[0]
        return ifaces[0] if ifaces else None

    def get_mac(self, iface: str) -> str:
        return ""

    def get_hostname(self) -> str:
        return ""

    def get_dns(self) -> list[str]:
        return []

    # ------------------------------------------------------------------ #
    # actions (overridden per platform)
    # ------------------------------------------------------------------ #
    def spoof_mac(self, iface, mac):
        return StepResult("MAC address", "skip", "not supported on this platform"), None

    def restore_mac(self, backup):
        return StepResult("MAC address", "fail", "nothing to restore")

    def set_hostname(self, name):
        return StepResult("Hostname", "skip", "not supported on this platform"), None

    def restore_hostname(self, backup):
        return StepResult("Hostname", "fail", "nothing to restore")

    def quiet_broadcasts(self):
        return StepResult("LAN broadcasts", "skip", "not supported on this platform"), None

    def restore_broadcasts(self, backup):
        return StepResult("LAN broadcasts", "fail", "nothing to restore")

    def private_dns(self, provider):
        return StepResult("Encrypted DNS", "skip", "not supported on this platform"), None

    def restore_dns(self, backup):
        return StepResult("Encrypted DNS", "fail", "nothing to restore")
