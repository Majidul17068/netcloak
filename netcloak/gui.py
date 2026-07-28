"""netcloak desktop app — a small Tkinter window: Cloak / Restore + tunnel.

Runs at normal-user level; privileged actions go through elevate.run_elevated,
which shows the native admin prompt. All work happens on background threads so
the window never freezes, and results are marshalled back with root.after().
"""
from __future__ import annotations

import os
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

from .backends import get_backend
from .elevate import run_elevated
from .state import has_state, has_tunnel, load_tunnel
from .util import DNS_PROVIDERS


class NetcloakGUI:
    def __init__(self, root):
        self.root = root
        self.be = get_backend()
        root.title("netcloak")
        root.resizable(False, False)
        self._build()
        self._refresh_async()

    # ------------------------------------------------------------------ #
    # layout
    # ------------------------------------------------------------------ #
    def _build(self):
        frm = ttk.Frame(self.root, padding=16)
        frm.grid(sticky="nsew")

        ttk.Label(frm, text="netcloak", font=("", 18, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            frm,
            text="Reduce what this network learns about your device.",
            foreground="#777",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.vars = {k: tk.StringVar(value="…") for k in ("iface", "mac", "host", "dns", "state")}
        box = ttk.LabelFrame(frm, text="Current", padding=10)
        box.grid(row=2, column=0, columnspan=2, sticky="ew")
        labels = [
            ("Interface", "iface"),
            ("MAC address", "mac"),
            ("Hostname", "host"),
            ("DNS", "dns"),
            ("Status", "state"),
        ]
        for i, (text, key) in enumerate(labels):
            ttk.Label(box, text=text + ":").grid(row=i, column=0, sticky="w")
            ttk.Label(box, textvariable=self.vars[key], font=("Menlo", 11)).grid(
                row=i, column=1, sticky="w", padx=(10, 0)
            )

        opts = ttk.Frame(frm)
        opts.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(opts, text="Encrypted DNS:").grid(row=0, column=0, sticky="w")
        self.dns_var = tk.StringVar(value="cloudflare")
        ttk.OptionMenu(opts, self.dns_var, "cloudflare", *DNS_PROVIDERS).grid(
            row=0, column=1, padx=(8, 0)
        )

        buttons = ttk.Frame(frm)
        buttons.grid(row=4, column=0, columnspan=2, pady=(12, 0))
        self.cloak_btn = ttk.Button(buttons, text="Cloak me", command=self.cloak)
        self.cloak_btn.grid(row=0, column=0, padx=4)
        self.restore_btn = ttk.Button(buttons, text="Restore", command=self.restore)
        self.restore_btn.grid(row=0, column=1, padx=4)

        tun = ttk.LabelFrame(frm, text="Tunnel — hide where traffic goes", padding=10)
        tun.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.tun_var = tk.StringVar(value="off")
        for i, (text, val) in enumerate([("Off", "off"), ("Tor", "tor"), ("WireGuard", "wg")]):
            ttk.Radiobutton(
                tun, text=text, variable=self.tun_var, value=val, command=self._on_tunnel_change
            ).grid(row=0, column=i, sticky="w")

        # WireGuard-only row — the .conf picker is enabled only when WireGuard is chosen
        self.wg_path = tk.StringVar(value="")
        self.conf_btn = ttk.Button(
            tun, text="Choose .conf file…", command=self.pick_conf, state="disabled"
        )
        self.conf_btn.grid(row=1, column=0, pady=(6, 0), sticky="w")
        self.conf_label = ttk.Label(tun, text="", foreground="#777")
        self.conf_label.grid(row=1, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(6, 0))

        self.apply_btn = ttk.Button(tun, text="Apply tunnel", command=self.apply_tunnel)
        self.apply_btn.grid(row=2, column=0, columnspan=3, pady=(10, 0))
        ttk.Label(
            tun, text="Off + Apply stops the tunnel.", foreground="#999"
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.log = scrolledtext.ScrolledText(
            frm, height=6, width=54, state="disabled", font=("Menlo", 10)
        )
        self.log.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _busy(self, busy):
        state = "disabled" if busy else "normal"
        for b in (self.cloak_btn, self.restore_btn, self.apply_btn):
            b.configure(state=state)

    def _on_tunnel_change(self):
        """Enable the .conf picker only for WireGuard; hint what to do next."""
        is_wg = self.tun_var.get() == "wg"
        self.conf_btn.configure(state="normal" if is_wg else "disabled")
        if not is_wg:
            self.conf_label.configure(text="")
        elif self.wg_path.get():
            self.conf_label.configure(text=os.path.basename(self.wg_path.get()))
        else:
            self.conf_label.configure(text="← choose your .conf, then click Apply")

    def pick_conf(self):
        path = filedialog.askopenfilename(
            title="Select WireGuard config",
            filetypes=[("WireGuard config", "*.conf"), ("All files", "*.*")],
        )
        if path:
            self.wg_path.set(path)
            self.tun_var.set("wg")
            self._on_tunnel_change()

    def _stage_conf(self, path):
        """Copy the picked .conf to a location the elevated helper can always read.

        Works the same on every OS: read the file here in the normal-user GUI
        (which is allowed — the file was just picked), then copy it into the OS
        temp dir before elevating. This sidesteps macOS's block on
        Downloads/Desktop/Documents for root-launched apps and keeps behaviour
        uniform on Linux and Windows, so a user can upload a .conf from anywhere.
        """
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                data = fh.read()
        except OSError as exc:
            self._log(f"Can't read the selected file: {exc}")
            return None
        dest = os.path.join(tempfile.gettempdir(), "netcloak-active.conf")
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(data)
        except OSError as exc:
            self._log(f"Can't stage the config: {exc}")
            return None
        return dest

    # ------------------------------------------------------------------ #
    # status refresh (background)
    # ------------------------------------------------------------------ #
    def _refresh_async(self):
        def work():
            try:
                di = self.be.default_interface()
                data = {
                    "iface": f"{di.name} ({di.kind})" if di else "—",
                    "mac": (self.be.get_mac(di.name) if di else "") or "—",
                    "host": self.be.get_hostname() or "—",
                    "dns": ", ".join(self.be.get_dns()) or "—",
                    "cloaked": has_state(),
                    "tunnel": has_tunnel(),
                }
            except Exception as exc:  # noqa: BLE001
                data = {"error": str(exc)}
            self.root.after(0, lambda: self._apply_status(data))

        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, d):
        if "error" in d:
            self._log("status error: " + d["error"])
            return
        self.vars["iface"].set(d["iface"])
        self.vars["mac"].set(d["mac"])
        self.vars["host"].set(d["host"])
        self.vars["dns"].set(d["dns"])
        self.vars["state"].set("●  CLOAKED" if d["cloaked"] else "○  not cloaked")
        self.cloak_btn.configure(state="disabled" if d["cloaked"] else "normal")
        self.restore_btn.configure(state="normal" if d["cloaked"] else "disabled")
        if d["tunnel"]:
            t = load_tunnel()
            self.tun_var.set("wg" if t.get("kind") == "wireguard" else "tor")
        self._on_tunnel_change()

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #
    def _run(self, args, label):
        self._busy(True)
        self._log(f"→ {label}…  (approve the admin prompt)")

        def work():
            ok, text = run_elevated(args)
            self.root.after(0, lambda: self._done(ok, text, label))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok, text, label):
        tail = text.strip().splitlines()[-1] if text.strip() else ("done" if ok else "failed")
        self._log(("✓ " if ok else "✗ ") + f"{label}: {tail}")
        self._busy(False)
        self._refresh_async()

    def cloak(self):
        self._run(["on", "--dns", self.dns_var.get()], "Cloak")

    def restore(self):
        self._run(["off"], "Restore")

    def apply_tunnel(self):
        choice = self.tun_var.get()
        if choice == "off":
            if not has_tunnel():
                self._log("No tunnel is active.")
                return
            self._run(["tunnel", "down"], "Tunnel off")
            return
        if choice == "wg":
            if not self.wg_path.get():
                self._log("Select a WireGuard .conf first — click 'Choose .conf file…'.")
                return
            staged = self._stage_conf(self.wg_path.get())
            if not staged:
                return  # _stage_conf already logged why
            args = ["tunnel", "up", "--wg", staged]
        else:
            args = ["tunnel", "up", "--tor"]

        if has_tunnel():  # switch: bring the old one down first, then up
            self._busy(True)
            self._log("→ switching tunnel…  (you may be prompted twice)")

            def work():
                run_elevated(["tunnel", "down"])
                ok, text = run_elevated(args)
                self.root.after(0, lambda: self._done(ok, text, "Tunnel"))

            threading.Thread(target=work, daemon=True).start()
        else:
            self._run(args, "Tunnel")


def launch():
    root = tk.Tk()
    try:
        style = ttk.Style()
        for theme in ("aqua", "vista", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
    except Exception:  # noqa: BLE001
        pass
    NetcloakGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
