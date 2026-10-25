#!/usr/bin/env python3
"""Print a one-page health report for the AOSP Bluetooth + DiPlay setup.

Usage:
    python doctor.py --target 192.168.1.23:5555

Checks:
    - adb reachability and root
    - Bluetooth manager state (12 = ON)
    - com.android.bluetooth UID / persistent flag
    - HAL and vendor library presence in both partitions
    - /dev/stpbt permissions
    - DiPlay wireless preferences
    - Wi-Fi interface mode

License: Apache-2.0
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

ADB = os.environ.get("ADB") or shutil.which("adb") or "adb"


def adb(target: str, *args: str, timeout: int = 60) -> str:
    proc = subprocess.run([ADB, "-s", target, *args],
                          capture_output=True, timeout=timeout)
    return (proc.stdout + proc.stderr).decode("utf-8", "ignore").strip()


def sh(target: str, command: str) -> str:
    return adb(target, "shell", command)


def root_sh(target: str, command: str) -> str:
    return sh(target, f"su 0 sh -c '{command}'")


def row(name: str, ok: bool | None, detail: str) -> None:
    mark = "OK  " if ok else ("WARN" if ok is None else "FAIL")
    print(f"  [{mark}] {name:<26} {detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True, help="ip:5555")
    args = ap.parse_args()
    t = args.target

    print(f"== DiPlay / Bluedroid doctor — {t} ==\n")
    adb(t, "connect", t, timeout=30)
    if "device" not in adb(t, "get-state"):
        print("[FAIL] device not reachable")
        return 2

    ident = sh(t, "id")
    is_root = "uid=0" in ident
    row("adb root", is_root, ident.split(" ")[0] if ident else "no shell")

    state = sh(t, "dumpsys bluetooth_manager | grep -i 'state:'")
    m = re.search(r"state:\s*(\d+)", state)
    bt_state = int(m.group(1)) if m else -1
    row("bluetooth state", bt_state == 12, f"{bt_state} (12 = ON)")

    pkg = sh(t, "dumpsys package com.android.bluetooth")
    uid_m = re.search(r"userId=(\d+)", pkg)
    uid = int(uid_m.group(1)) if uid_m else -1
    persistent = "PERSISTENT" in pkg
    row("bluetooth UID", uid == 1002, str(uid))
    row("persistent flag", persistent, "yes" if persistent else "missing")

    for path in ("/system/lib/hw/bluetooth.default.so",
                 "/system/vendor/lib/hw/bluetooth.default.so",
                 "/system/lib/libbt-vendor.so",
                 "/system/vendor/lib/libbt-vendor.so"):
        out = root_sh(t, f"ls -l {path} 2>/dev/null")
        row(path.rsplit('/', 1)[-1] if 'hw/' not in path else 'hw/' + path.rsplit('/', 1)[-1],
            bool(out), out.split()[-1] if out else "absent")

    node = root_sh(t, "ls -l /dev/stpbt /dev/ivt_stpbt 2>/dev/null")
    row("/dev/stpbt", "/dev/stpbt" in node and "666" in node,
        node.replace("\n", " | ") or "absent")

    prefs = root_sh(t, "cat /data/data/com.shihab.diplay/shared_prefs/"
                       "xcertplay_airplay.xml 2>/dev/null")
    mode = re.search(r'wireless_hotspot_mode">([^<]+)<', prefs)
    ssid = re.search(r'existing_wifi_ssid">([^<]+)<', prefs)
    row("diplay mode", bool(mode), mode.group(1) if mode else "unset")
    row("diplay wifi ssid", bool(ssid), ssid.group(1) if ssid else "unset")
    row("diplay wifi password", None,
        "set" if "existing_wifi_passphrase" in prefs and
        'passphrase"></string>' not in prefs else "missing")

    wlan = sh(t, "ip addr show wlan0 | grep inet")
    row("wlan0", bool(wlan), wlan.split()[1] if wlan else "down")

    print("\nLogs worth checking:")
    print("  adb -s %s logcat -d | grep -iE 'HOTSPOT|PAIRING|bt_vendor_mtk|bt-btu'" % t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
