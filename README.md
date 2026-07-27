# netcloak

Reduce what a local network (router / Wi-Fi admin) can passively learn about
**your own device** — cross-platform (macOS, Linux, Windows), and fully
reversible.

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
├── cli.py            # on / off / status / interfaces / tunnel
├── tunnel.py         # WireGuard + Tor
├── state.py          # reversible backups
├── util.py privileges.py
└── backends/
    ├── base.py       # shared interface
    ├── linux.py macos.py windows.py
```

## Legal / ethics

Use netcloak only on networks you **own or are explicitly authorised to use**.
MAC randomisation is a standard privacy feature (iOS/Android/Windows/macOS all
ship it), but spoofing identifiers on networks you don't control may violate
their terms of service or local law. You are responsible for how you use it.
