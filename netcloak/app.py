"""Unified entry point.

No arguments (e.g. a double-clicked app) -> launch the GUI.
Any arguments -> run the command-line interface. This lets a single packaged
binary serve both the click-to-run users and the elevated CLI calls the GUI
makes under the hood.
"""
from __future__ import annotations

import sys


def app_main():
    argv = sys.argv[1:]
    if not argv or argv[0] == "gui":
        from .gui import launch

        launch()
        return
    from .cli import main

    main(argv)
