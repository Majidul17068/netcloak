# netcloak

Reduce what a local network (router / Wi-Fi admin) can passively learn about
**your own device** — cross-platform (macOS, Linux, Windows), and fully
reversible.

## Download & run (no Python needed)

Grab the file for your OS from the
[**Releases**](https://github.com/Majidul17068/netcloak/releases) page and open
it — it's a normal desktop app with **Cloak / Restore** buttons and a tunnel
switch.

| OS | Download | First run |
|----|----------|-----------|
| **Windows** | `netcloak-windows.exe` | Double-click. If SmartScreen warns: *More info → Run anyway*. |
| **macOS** | `netcloak-macos.zip` | Unzip, then **right-click → Open** (unsigned app). If blocked: `xattr -dr com.apple.quarantine netcloak.app`. |
| **Linux** | `netcloak-linux` | `chmod +x netcloak-linux && ./netcloak-linux` |

When you click **Cloak**, the app asks for your admin password (Windows UAC /
macOS password / Linux polkit). That prompt is required to change the MAC
address and cannot be removed — it's the operating system protecting itself.

Prefer the terminal? The same commands work from source:

```bash
sudo python3 -m netcloak status        # show current MAC / hostname / DNS
sudo python3 -m netcloak on            # cloak the active interface
sudo python3 -m netcloak off           # restore everything
```

## What it does

| Step | Effect | Who it hides you from |
|------|--------|-----------------------|
| **MAC randomisation** | Random locally-administered MAC before you connect | The *local* network segment only |
| **Hostname strip** | Generic `DESKTOP-XXXXXXX`, no name leaked over DHCP | DHCP server / admin |
| **Silence broadcasts** | Turns off mDNS / LLMNR / NetBIOS chatter | Everyone on the same LAN |
| **Encrypted DNS** | DoH / DoT to Cloudflare / Quad9 / AdGuard | Stops the admin logging your lookups |

Everything it changes is written to a state file (`/var/lib/netcloak/state.json`,
`~/.netcloak/`, or `%PROGRAMDATA%\netcloak`) and undone by `off`.

## ⚠️ What it does NOT do — read this

netcloak hides your **device identity** and your **DNS lookups**. It does **not**
hide **which websites you visit**. Your router/admin can still see:

- the **destination IP** of every connection, and
- the **server name (SNI)** inside each TLS handshake.

**To hide where your browsing goes, you must tunnel your traffic** through an
encrypted channel that terminates *outside* the admin's network:

- **VPN** (WireGuard) — everything after the router sees only the VPN's IP.
  Requires a VPN provider or your own server.
- **Tor** — free, hides destinations, but slower and blockable by some networks.

netcloak ships a `tunnel` module for exactly this — see **Tunnel** below.

Other honest limits:

- **macOS (Apple Silicon / T2):** the Wi-Fi driver often reverts a spoofed MAC —
  the tool detects this and reports `fail` rather than lying. mDNS can't be
  safely disabled on macOS, so that step is skipped. True DoH needs the
  generated `.mobileconfig` profile installed in System Settings.
- **Windows:** hostname change needs a reboot; some adapters/drivers refuse MAC
  changes. DoH is Windows 11+.
- Logging into a captive portal or any account re-identifies you regardless.
- Some networks **block unknown MACs** — spoofing there just loses you access.

## Install

No third-party dependencies — Python 3.8+ only. Run it in place:

```bash
python3 -m netcloak --help
```

Or install the `netcloak` command:

```bash
pip install .
```

## Usage

```bash
sudo python3 -m netcloak interfaces              # list adapters
sudo python3 -m netcloak on -i en0               # pick an interface
sudo python3 -m netcloak on --dns quad9          # choose DNS provider
sudo python3 -m netcloak on --keep-oui 3c:22:fb  # keep a real vendor prefix
sudo python3 -m netcloak on --no-hostname        # skip individual steps
sudo python3 -m netcloak off                     # revert everything
```

## Tunnel — hide where traffic goes

The device layer above hides *who* you are; the tunnel layer hides *where you
go*. Bring up **one** tunnel at a time:

```bash
# WireGuard: point at any provider's .conf (Mullvad, Proton, your own server)
sudo python3 -m netcloak tunnel up --wg ~/wg0.conf

# Tor: launches a local Tor daemon and routes the system SOCKS proxy through it
sudo python3 -m netcloak tunnel up --tor

sudo python3 -m netcloak tunnel status
sudo python3 -m netcloak tunnel down             # stop + restore proxy settings
```

Requirements: WireGuard needs `wg-quick` (`brew/apt install wireguard-tools`)
or the WireGuard app on Windows; Tor needs the `tor` daemon (`brew/apt install
tor`). For the strongest anonymity, prefer the **Tor Browser** over the system
SOCKS proxy — it also defeats browser fingerprinting, which netcloak does not.

## Project layout

```
netcloak/
├── app.py            # entry: no args → GUI, args → CLI
├── gui.py            # Tkinter desktop app
├── elevate.py        # UAC / password / polkit prompt
├── cli.py            # on / off / status / interfaces / tunnel
├── tunnel.py         # WireGuard + Tor
├── state.py          # reversible backups
├── util.py privileges.py
└── backends/
    ├── base.py       # shared interface
    ├── linux.py macos.py windows.py
packaging/            # PyInstaller entry point
.github/workflows/    # auto-build Win/Mac/Linux apps
```

## Releasing (maintainer)

Binaries are built automatically by GitHub Actions — no build tools needed
locally. To publish a downloadable set:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The `build` workflow compiles the Windows/macOS/Linux apps and attaches them to
a GitHub Release. You can also trigger it from the **Actions → build → Run
workflow** button, which uploads the binaries as run artifacts for testing
before you tag.

## Legal / ethics

Use netcloak only on networks you **own or are explicitly authorised to use**.
MAC randomisation is a standard privacy feature (iOS/Android/Windows/macOS all
ship it), but spoofing identifiers on networks you don't control may violate
their terms of service or local law. You are responsible for how you use it.
