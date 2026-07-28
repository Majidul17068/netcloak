<h1 align="center">netcloak</h1>

<p align="center">
  <b>Reduce what any network can learn about you — in one click.</b><br>
  Randomize your MAC, mask your hostname, encrypt DNS, and tunnel your traffic
  through WireGuard or <i>Tor-over-VPN</i>. Cross-platform desktop app. Fully reversible.
</p>

<p align="center">
  <a href="https://github.com/Majidul17068/netcloak/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/Majidul17068/netcloak"></a>
  <img alt="Platforms" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-blue">
  <img alt="Python" src="https://img.shields.io/badge/python-3.8%2B-blue">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
  <img alt="Dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen">
</p>

---

**netcloak** is a small privacy app that stops the network you're connected to
(the café Wi-Fi, your ISP, a hotel router) from identifying your device or
seeing where you browse. Every change is a toggle — one click cloaks you, one
click puts everything back exactly as it was. No accounts, no telemetry, no
third-party dependencies.

## Why netcloak

- 🕵️ **The network can't tell who your device is** — random MAC, generic hostname, no chatty broadcasts
- 🔒 **The network can't read your DNS lookups** — encrypted DNS (DoH/DoT)
- 🌍 **The network can't see where you browse** — WireGuard VPN, or **Tor-over-VPN** that even defeats ISP-level Tor blocking
- 🧯 **Kill switch** — if the VPN drops, traffic is blocked instead of leaking
- ↩️ **Fully reversible** — everything is backed up and restored on "off"; a reboot also resets it
- 💻 **One binary, three OSes** — double-click app for macOS, Linux, and Windows
- 🪶 **Zero dependencies** — pure Python standard library

## Download & run

Grab your OS's file from the **[latest release](https://github.com/Majidul17068/netcloak/releases/latest)** and open it — it's a normal desktop app.

| OS | Download | First run |
|----|----------|-----------|
| **macOS** | [`netcloak-macos.zip`](https://github.com/Majidul17068/netcloak/releases/latest/download/netcloak-macos.zip) | Unzip → **right-click → Open**. If blocked: `xattr -dr com.apple.quarantine netcloak.app` |
| **Windows** | [`netcloak-windows.exe`](https://github.com/Majidul17068/netcloak/releases/latest/download/netcloak-windows.exe) | Double-click. SmartScreen → *More info → Run anyway*. On Smart App Control, run from source (below) |
| **Linux** | [`netcloak-linux`](https://github.com/Majidul17068/netcloak/releases/latest/download/netcloak-linux) | `chmod +x netcloak-linux && ./netcloak-linux` |

> Changing your MAC / firewall needs admin rights, so the app asks for your
> password (macOS) / UAC (Windows) / polkit (Linux) when you click **Cloak** or
> apply a tunnel. That prompt is the OS protecting itself and can't be removed.

Prefer Python? `pip install .` then run `netcloak`, or `python3 -m netcloak`.

## The two layers

netcloak works in two independent layers you can mix and match:

| Layer | Button | Hides | Who from |
|---|---|---|---|
| **Cloak** | *Cloak me* | your **device** (MAC, hostname, DNS) | the local Wi-Fi / router admin |
| **Tunnel** | *WireGuard / Tor* | **where you browse** (destination IP, SNI) | the network **and** your ISP |

- **Cloak** = anonymous device on the LAN.
- **Tunnel** = hidden browsing.
- **Both** = anonymous device *and* hidden browsing — the full picture a local network can see.

### Tunnel options

| Mode | Needs | Best for |
|---|---|---|
| **WireGuard** | any provider's `.conf` (Proton, Mullvad, self-hosted…) | fast, reliable everyday VPN |
| **Tor** | nothing (auto-installed) | free destination-hiding on open networks |
| **Tor-over-VPN** ⭐ | WireGuard `.conf` + tick *"Also route through Tor"* | **networks that block Tor**, and max anonymity — no single party links you to your destination |

netcloak is **provider-agnostic**: it accepts *any* WireGuard `.conf`, so you're never locked to one vendor. Missing runtimes (Tor, `wireguard-tools`) are **auto-installed** on first use via Homebrew / apt / winget.

## Usage

**GUI:** open the app → **Cloak me** → choose **WireGuard** and upload your `.conf` (optionally tick **Tor** and **Kill switch**) → **Apply**. **Restore** and **Off → Apply** put everything back.

**CLI:**
```bash
sudo python3 -m netcloak status                    # show current MAC / hostname / DNS
sudo python3 -m netcloak on                         # cloak device identity + encrypted DNS
sudo python3 -m netcloak on --dns quad9             # pick a DNS provider
sudo python3 -m netcloak off                        # undo the cloak

sudo python3 -m netcloak tunnel up --wg proton.conf # VPN
sudo python3 -m netcloak tunnel up --wg proton.conf --via-tor --kill-switch   # max anonymity
sudo python3 -m netcloak tunnel up --tor            # Tor only
sudo python3 -m netcloak tunnel down                # stop the tunnel + lift kill switch
```

## What netcloak protects — and what it doesn't

A privacy tool you can trust is one that's honest about its limits.

**It protects you from the network you're on.** With Cloak + a tunnel, the Wi-Fi
owner / router admin / ISP cannot identify your device or see the sites you visit.

**It is _not_ full anonymity, and it is _not_ anti-malware:**

- **You logging in de-anonymizes you.** Sign into Gmail/Facebook/your bank and you're identified regardless of MAC or VPN. Behavior is the weakest link.
- **A VPN moves trust; it doesn't erase it.** Your VPN provider can see your traffic (Tor-over-VPN fixes this by hiding destinations even from the VPN).
- **Browser fingerprinting** (canvas, fonts, screen) still identifies your browser — use **Tor Browser** for that; netcloak doesn't touch the browser.
- **It won't stop a hacker attacking your device.** It's a *privacy* tool, not a firewall for your machine. Turn on your OS firewall + stealth mode, disable unused sharing, and keep software patched.
- **No tool makes you "completely anonymous."** The realistic goal is to make identifying you cost far more than you're worth to whoever's looking.

Closest-to-anonymous setup: **Cloak + WireGuard + Tor-over-VPN + kill switch → browse in Tor Browser → never log into identifying accounts.**

## Platform notes

- **macOS (Apple Silicon):** the Wi-Fi driver often reverts a spoofed MAC — netcloak reports this honestly instead of pretending. WireGuard uses the userspace `wireguard-go` backend (auto-installed).
- **Windows:** hostname change needs a reboot; DoH is Windows 11+. **Smart App Control** blocks unsigned `.exe`s outright — run from source (Python) on those machines.
- **Linux:** needs a graphical session for the GUI; the CLI works headless. wg-quick provides a route-based kill switch for full-tunnel configs.

## How it's built

```
netcloak/
├── app.py            # entry: no args → GUI, args → CLI
├── gui.py            # Tkinter desktop app (Cloak / Restore / Tunnel)
├── cli.py            # on / off / status / interfaces / tunnel
├── elevate.py        # native admin prompt (UAC / password / polkit)
├── tunnel.py         # WireGuard + Tor + Tor-over-VPN
├── killswitch.py     # pf / route-based leak protection
├── deps.py           # auto-install Tor / WireGuard
├── state.py          # reversible backups
└── backends/         # per-OS: linux.py · macos.py · windows.py
packaging/            # PyInstaller entry point
.github/workflows/    # auto-builds macOS / Linux / Windows apps on tag
```

Backends implement one interface, so the CLI/GUI contain no OS-specific code.
Every action returns a backup that's saved to a state file and replayed on
`off` — that's the reversibility guarantee.

## Build & release (maintainers)

```bash
pip install -e .          # dev install
python3 -m netcloak --help

git tag v0.2.1 && git push origin v0.2.1   # → CI builds all 3 apps, attaches to a Release
```

The `build` workflow (GitHub Actions) compiles the Windows/macOS/Linux binaries
with PyInstaller and attaches them to the release. Trigger it manually from
**Actions → build → Run workflow** to test before tagging.

## Legal & ethics

Use netcloak only on networks you **own or are authorized to use**. MAC
randomization is a standard privacy feature (iOS/Android/Windows/macOS all ship
it), but spoofing identifiers or bypassing controls on networks you don't
control may violate their terms of service or local law. You are responsible for
how you use it.

## License

[MIT](LICENSE) © Majidul Islam
