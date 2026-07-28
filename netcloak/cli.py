"""netcloak command-line interface."""
from __future__ import annotations

import argparse
import platform
import sys

from . import __version__
from .backends import get_backend
from .privileges import elevation_hint, is_admin
from .state import (
    clear_state,
    clear_tunnel,
    has_state,
    has_tunnel,
    load_state,
    load_tunnel,
    save_state,
    save_tunnel,
)
from .tunnel import tor_down, tor_up, wireguard_down, wireguard_up
from .util import (
    DNS_PROVIDERS,
    err,
    hr,
    info,
    ok,
    random_hostname,
    random_mac,
    title,
    warn,
)


def _print(result):
    {"ok": ok, "skip": warn, "fail": err}.get(result.status, info)(
        f"{result.name}: {result.message}"
    )


def cmd_interfaces(be, args):
    title("Network interfaces")
    for i in be.list_interfaces():
        mark = "→" if i.active else " "
        info(f"{mark} {i.name:<12} {i.mac or '(no mac)':<18} {i.kind}")


def cmd_status(be, args):
    title("Current network identity")
    di = be.default_interface()
    if di:
        info(f"Active interface : {di.name} ({di.kind})")
        info(f"MAC address      : {be.get_mac(di.name)}")
    info(f"Hostname         : {be.get_hostname()}")
    dns = be.get_dns()
    info(f"DNS servers      : {', '.join(dns) if dns else '(unknown)'}")
    hr()
    if has_state():
        st = load_state().get("meta", {})
        warn(f"netcloak is ACTIVE on {st.get('iface', '?')}. Run `off` to revert.")
    else:
        info("netcloak is not active.")


def cmd_on(be, args):
    if not is_admin():
        err("Administrator / root privileges required.")
        info(elevation_hint())
        sys.exit(1)
    if has_state():
        warn("Already active. Run `off` first (or `off` then `on` to re-roll identity).")
        sys.exit(1)

    iface = args.interface
    if not iface:
        di = be.default_interface()
        if not di:
            err("Could not detect a network interface — pass --interface.")
            sys.exit(1)
        iface = di.name

    state = {"meta": {"iface": iface, "platform": platform.system()}}
    title(f"Cloaking {iface}")

    if not args.no_mac:
        result, backup = be.spoof_mac(iface, random_mac(keep_oui=args.keep_oui))
        _print(result)
        if backup is not None:
            state["mac"] = backup
    if not args.no_hostname:
        result, backup = be.set_hostname(args.hostname or random_hostname())
        _print(result)
        if backup is not None:
            state["hostname"] = backup
    if not args.no_broadcasts:
        result, backup = be.quiet_broadcasts()
        _print(result)
        if backup is not None:
            state["broadcasts"] = backup
    if not args.no_dns:
        result, backup = be.private_dns(args.dns)
        _print(result)
        if backup is not None:
            state["dns"] = backup

    save_state(state)
    hr()
    ok("State saved — run `netcloak off` to restore everything.")
    warn("Scope: this hides your DEVICE on the LAN and encrypts DNS lookups.")
    warn("It does NOT hide which sites you visit (destination IP + TLS SNI stay")
    warn("visible). To hide that too, tunnel through a VPN or Tor — see the README.")


def cmd_off(be, args):
    if not is_admin():
        err("Administrator / root privileges required.")
        info(elevation_hint())
        sys.exit(1)
    if not has_state():
        warn("Nothing to restore (no saved state).")
        return
    st = load_state()
    title("Restoring original settings")
    if "mac" in st:
        _print(be.restore_mac(st["mac"]))
    if "hostname" in st:
        _print(be.restore_hostname(st["hostname"]))
    if "broadcasts" in st:
        _print(be.restore_broadcasts(st["broadcasts"]))
    if "dns" in st:
        _print(be.restore_dns(st["dns"]))
    clear_state()
    hr()
    ok("Restored. netcloak is no longer active.")


def cmd_tunnel(be, args):
    action = args.tunnel_action
    if action == "status":
        title("Tunnel")
        if has_tunnel():
            t = load_tunnel()
            ok(f"Active: {t.get('kind')} — traffic destinations are hidden from the LAN.")
        else:
            info("No tunnel active. Your destination IPs / SNI are visible to the network.")
        return

    if not is_admin():
        err("Administrator / root privileges required.")
        info(elevation_hint())
        sys.exit(1)

    if action == "up":
        if has_tunnel():
            warn("A tunnel is already active. Run `tunnel down` first.")
            sys.exit(1)
        if bool(args.wg) == bool(args.tor):
            err("Choose one base: --wg <config.conf>  or  --tor")
            sys.exit(1)
        if args.via_tor and not args.wg:
            err("--via-tor needs --wg (Tor runs on top of the WireGuard tunnel)")
            sys.exit(1)
        title("Bringing tunnel up")

        if args.tor:
            result, state = tor_up()
            _print(result)
            if state is None:
                sys.exit(1)
        else:
            wg_result, wg_state = wireguard_up(args.wg)
            _print(wg_result)
            if wg_state is None or wg_result.status != "ok":
                sys.exit(1)
            state = wg_state
            if args.via_tor:
                # Tor now connects *through* the WireGuard tunnel, so an ISP that
                # blocks Tor never sees it — and Proton no longer sees destinations.
                tor_result, tor_state = tor_up()
                _print(tor_result)
                if tor_state is not None and tor_result.status == "ok":
                    state = {"kind": "wg+tor", "wg": wg_state, "tor": tor_state}
                else:
                    warn("Tor-over-VPN didn't start; the WireGuard tunnel is still up.")

        save_tunnel(state)
        hr()
        ok("Tunnel state saved — run `netcloak tunnel down` to stop.")
        if state.get("kind") == "wg+tor":
            info("Tor-over-VPN active: set your browser's SOCKS proxy to 127.0.0.1:9050")
            info("(or use Tor Browser). Tor needs ~30s to bootstrap.")
        return

    if action == "down":
        if not has_tunnel():
            warn("No tunnel active.")
            return
        t = load_tunnel()
        title("Bringing tunnel down")
        kind = t.get("kind")
        if kind == "wg+tor":
            _print(tor_down(t["tor"]))
            _print(wireguard_down(t["wg"]))
        elif kind == "wireguard":
            _print(wireguard_down(t))
        else:
            _print(tor_down(t))
        clear_tunnel()
        hr()
        ok("Tunnel stopped.")


def build_parser():
    p = argparse.ArgumentParser(
        prog="netcloak",
        description=(
            "Reduce what a local network passively learns about your device. "
            "Use ONLY on networks you own or are authorised to use."
        ),
    )
    p.add_argument("--version", action="version", version=f"netcloak {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("interfaces", help="list network interfaces")
    sub.add_parser("status", help="show current MAC / hostname / DNS")

    on = sub.add_parser("on", help="apply cloaking")
    on.add_argument("-i", "--interface", help="interface to cloak (default: active one)")
    on.add_argument("--hostname", help="hostname to use (default: random DESKTOP-XXXXXXX)")
    on.add_argument("--keep-oui", help="preserve a real vendor OUI, e.g. 3c:22:fb")
    on.add_argument(
        "--dns", choices=list(DNS_PROVIDERS), default="cloudflare", help="encrypted DNS provider"
    )
    on.add_argument("--no-mac", action="store_true", help="skip MAC randomisation")
    on.add_argument("--no-hostname", action="store_true", help="skip hostname change")
    on.add_argument("--no-broadcasts", action="store_true", help="skip silencing broadcasts")
    on.add_argument("--no-dns", action="store_true", help="skip encrypted DNS")

    sub.add_parser("off", help="revert everything netcloak changed")

    tun = sub.add_parser("tunnel", help="hide WHERE traffic goes (WireGuard or Tor)")
    tsub = tun.add_subparsers(dest="tunnel_action", required=True)
    tup = tsub.add_parser("up", help="bring a tunnel up")
    tup.add_argument("--wg", metavar="CONFIG", help="path to a WireGuard .conf file")
    tup.add_argument("--tor", action="store_true", help="route through Tor (SOCKS5)")
    tup.add_argument(
        "--via-tor",
        action="store_true",
        help="with --wg: also run Tor over the WireGuard tunnel (Tor-over-VPN)",
    )
    tsub.add_parser("down", help="stop the active tunnel")
    tsub.add_parser("status", help="show tunnel state")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        be = get_backend()
    except RuntimeError as exc:
        err(str(exc))
        sys.exit(2)
    {
        "interfaces": cmd_interfaces,
        "status": cmd_status,
        "on": cmd_on,
        "off": cmd_off,
        "tunnel": cmd_tunnel,
    }[args.cmd](be, args)
