#!/usr/bin/env python3
"""Find an Android head unit exposing ADB over Wi-Fi (tcp/5555).

Scans the /24 around each local IPv4 address, or the CIDRs you pass in.
No third-party dependencies.

Usage:
    python find_headunit.py
    python find_headunit.py --cidr 192.168.43.0/24 --cidr 10.0.0.0/24
    python find_headunit.py --timeout 1.2 --workers 256

Exit code is 0 when at least one candidate responds.

License: Apache-2.0
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import ipaddress
import socket
import subprocess
import sys

PORT = 5555


def local_ipv4() -> list[str]:
    """Best-effort list of local IPv4 addresses without external deps."""
    ips: list[str] = []

    # 1) UDP trick: does not send packets, just picks the egress interface.
    for probe in ("8.8.8.8", "1.1.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.3)
            s.connect((probe, 53))
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass

    # 2) Platform-specific enumeration, to cover multiple adapters.
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["ipconfig"], capture_output=True,
                                 text=True, errors="ignore").stdout
            for line in out.splitlines():
                if "IPv4" in line and ":" in line:
                    candidate = line.rsplit(":", 1)[-1].strip()
                    if candidate.count(".") == 3:
                        ips.append(candidate)
        else:
            out = subprocess.run(["sh", "-c", "ip -4 addr show 2>/dev/null || ifconfig"],
                                 capture_output=True, text=True, errors="ignore").stdout
            for token in out.replace("\n", " ").split():
                if token.count(".") == 3 and "/" in token:
                    ips.append(token.split("/")[0])
    except OSError:
        pass

    seen, result = set(), []
    for ip in ips:
        if ip.startswith(("127.", "169.254.", "0.")):
            continue
        if ip not in seen:
            seen.add(ip)
            result.append(ip)
    return result


def probe(ip: str, timeout: float) -> str | None:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((ip, PORT))
        return ip
    except OSError:
        return None
    finally:
        sock.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cidr", action="append", default=[],
                    help="network to scan, e.g. 192.168.43.0/24 (repeatable)")
    ap.add_argument("--timeout", type=float, default=0.7)
    ap.add_argument("--workers", type=int, default=192)
    ap.add_argument("--quiet", action="store_true",
                    help="print only `ip:5555` lines (for scripts)")
    args = ap.parse_args()

    def note(*parts: object) -> None:
        if not args.quiet:
            print(*parts)

    networks: list[ipaddress.IPv4Network] = []
    for cidr in args.cidr:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError as exc:
            print(f"error: bad --cidr {cidr}: {exc}", file=sys.stderr)
            return 2

    if not networks:
        for ip in local_ipv4():
            networks.append(ipaddress.ip_network(f"{ip}/24", strict=False))
            note(f"[*] local address {ip} -> scanning {ip}/24")

    if not networks:
        print("error: could not determine a local network; use --cidr", file=sys.stderr)
        return 2

    targets = []
    for net in networks:
        targets.extend(str(h) for h in net.hosts())

    note(f"[*] probing {len(targets)} address(es) on tcp/{PORT} ...")
    found: list[str] = []
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(lambda ip: probe(ip, args.timeout), targets):
            if result and result not in found:
                found.append(result)
                print(f"{result}:{PORT}" if args.quiet else f"[+] {result}:{PORT}")

    if not found:
        if not args.quiet:
            print("\n[!] no head unit found.")
            print("    - Is the head unit on the same L2 network as this PC?")
            print("    - Is wireless ADB enabled? (often a dialer code on the unit)")
            print("    - Some units only expose ADB after `adb tcpip 5555` over USB.")
        return 1

    if not args.quiet:
        print("\nNext:")
        for ip in found:
            print(f"  adb connect {ip}:{PORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
