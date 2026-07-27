"""Platform backend factory."""
from __future__ import annotations

import platform

from .base import Backend, Interface, StepResult  # noqa: F401


def get_backend() -> Backend:
    system = platform.system()
    if system == "Linux":
        from .linux import LinuxBackend

        return LinuxBackend()
    if system == "Darwin":
        from .macos import MacBackend

        return MacBackend()
    if system == "Windows":
        from .windows import WindowsBackend

        return WindowsBackend()
    raise RuntimeError(f"Unsupported platform: {system}")
