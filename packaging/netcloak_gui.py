"""PyInstaller entry point.

Double-clicking the built binary launches the GUI; when the GUI re-invokes the
binary with arguments (elevated), the same entry routes to the CLI.
"""
from netcloak.app import app_main

if __name__ == "__main__":
    app_main()
