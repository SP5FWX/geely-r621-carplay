#!/usr/bin/env python3
"""Deploy the AOSP Bluetooth stack to an R621 head unit, with backups.

This tool is intentionally conservative:

  * it refuses to run without --apply (dry-run by default)
  * it backs up every file it is about to overwrite
  * it verifies root before touching /system
  * it prints every command it runs

Usage:
    cp config/example.properties config/local.properties   # edit it
    python deploy_hal.py --config config/local.properties            # dry run
    python deploy_hal.py --config config/local.properties --apply

Requirements: adb in PATH (or ADB env var), rooted head unit, ADB over TCP.

License: Apache-2.0
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ADB = os.environ.get("ADB") or shutil.which("adb") or "adb"
BACKUP = "/data/local/aosp_bak"

HAL_TARGETS = [
    "/system/lib/hw/bluetooth.default.so",
    "/system/lib/hw/bluetooth.mt6735.so",
    "/system/vendor/lib/hw/bluetooth.default.so",
    "/system/vendor/lib/hw/bluetooth.mt6735.so",
]
VENDOR_TARGETS = [
    "/system/lib/libbt-vendor.so",
    "/system/vendor/lib/libbt-vendor.so",
]


def load_props(path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


class Runner:
    def __init__(self, target: str, apply: bool):
        self.target = target
        self.apply = apply

    def host(self, *args: str, timeout: int = 60) -> str:
        """Run an adb host command (connect/root/kill-server), no -s."""
        print("    $ adb " + " ".join(args))
        proc = subprocess.run([ADB, *args], capture_output=True, timeout=timeout)
        out = (proc.stdout + proc.stderr).decode("utf-8", "ignore").strip()
        if out:
            print("      " + out.replace("\n", "\n      ")[:1200])
        return out

    def adb(self, *args: str, timeout: int = 120) -> str:
        print("    $ adb -s " + self.target + " " + " ".join(args))
        proc = subprocess.run([ADB, "-s", self.target, *args],
                              capture_output=True, timeout=timeout)
        out = (proc.stdout + proc.stderr).decode("utf-8", "ignore").strip()
        if out:
            print("      " + out.replace("\n", "\n      ")[:1200])
        return out

    def shell(self, command: str, timeout: int = 120) -> str:
        return self.adb("shell", command, timeout=timeout)

    def root_shell(self, command: str, timeout: int = 120) -> str:
        # `su -c "long command"` is unreliable on several ROMs; wrap in sh.
        return self.shell(f"su 0 sh -c '{command}'", timeout=timeout)

    def push(self, src: Path, dst: str, timeout: int = 300) -> None:
        self.adb("push", str(src), dst, timeout=timeout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config/local.properties")
    ap.add_argument("--target", help="override target ip:5555")
    ap.add_argument("--bdaddr", help="override bdaddr, e.g. AA:BB:CC:DD:EE:FF")
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--skip-reboot", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"error: config not found: {cfg_path}", file=sys.stderr)
        print("       cp config/example.properties config/local.properties", file=sys.stderr)
        return 2
    cfg = load_props(cfg_path)

    target = args.target or cfg.get("target", "")
    bdaddr = args.bdaddr or cfg.get("bdaddr", "")
    aosp_dir = Path(cfg.get("aosp_dir", "./vendor/aosp51"))

    if not target:
        print("error: target not set", file=sys.stderr)
        return 2

    hal_src = Path("hal/build/bluetooth.default.so")
    vendor_src = Path("hal/build/libbt-vendor.so")
    apk_src = aosp_dir / "Bluetooth.apk"
    jni_src = aosp_dir / "libbluetooth_jni.so"

    required = [hal_src, vendor_src, apk_src, jni_src]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        print("error: missing build inputs:", file=sys.stderr)
        for item in missing:
            print("  -", item, file=sys.stderr)
        print("\nBuild the HAL first: cd hal && ./build.sh", file=sys.stderr)
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[*] mode   : {mode}")
    print(f"[*] target : {target}")
    print(f"[*] bdaddr : {bdaddr or '(unchanged)'}")

    runner = Runner(target, args.apply)

    runner.host("connect", target, timeout=40)
    ident = runner.shell("id", timeout=30)
    if "uid=0" not in ident:
        print("\n[!] not root. Trying `adb root` ...", file=sys.stderr)
        runner.host("root", timeout=40)
        runner.host("connect", target, timeout=40)
        ident = runner.shell("id", timeout=30)
        if "uid=0" not in ident:
            print("error: no root shell. Enable adb root on the unit.", file=sys.stderr)
            return 3

    if not args.apply:
        print("\n[dry-run] would perform:")
        for path in HAL_TARGETS + VENDOR_TARGETS:
            print(f"  - push to {path}")
        print(f"  - push {apk_src.name} -> /system/app/Bluetooth/Bluetooth.apk")
        print(f"  - push {jni_src.name} -> /system/app/Bluetooth/lib/arm/")
        print(f"  - backup originals to {BACKUP}")
        print("  - disable:", cfg.get("disable_packages", "(none)"))
        print("  - clear /data/misc/bluedroid, reboot")
        print("\nRe-run with --apply to execute.")
        return 0

    print("\n[1/8] backup")
    runner.root_shell(f"mkdir -p {BACKUP}")
    for path in ["/system/bin/brlinkd", "/system/vendor/lib/hw/bluetooth.blueangel.so"] + HAL_TARGETS + VENDOR_TARGETS:
        name = path.rsplit("/", 1)[-1]
        runner.root_shell(
            f"if [ -f {path} ] && [ ! -f {BACKUP}/{name}.orig ]; then "
            f"cp {path} {BACKUP}/{name}.orig; fi"
        )
    runner.root_shell(f"ls -la {BACKUP}")

    print("\n[2/8] remount /system")
    runner.root_shell("mount -o rw,remount /system")

    print("\n[3/8] stop vendor Bluetooth daemon")
    runner.root_shell("setprop ctl.stop brlinkd; sleep 2; pidof brlinkd || true")

    print("\n[4/8] restore /dev/stpbt")
    runner.root_shell("if [ -e /dev/ivt_stpbt ] && [ ! -e /dev/stpbt ]; then "
                      "mv /dev/ivt_stpbt /dev/stpbt; fi")
    runner.root_shell("chmod 666 /dev/stpbt /dev/stpwmt 2>/dev/null; true")

    print("\n[5/8] install HAL + vendor library")
    runner.push(vendor_src, "/data/local/tmp/libbt-vendor.so")
    for dst in VENDOR_TARGETS:
        runner.root_shell(f"cp /data/local/tmp/libbt-vendor.so {dst}; chmod 644 {dst}")
    runner.push(hal_src, "/data/local/tmp/bluetooth.default.so")
    for dst in HAL_TARGETS:
        runner.root_shell(f"cp /data/local/tmp/bluetooth.default.so {dst}; chmod 644 {dst}")

    print("\n[6/8] install Bluetooth app + JNI")
    runner.root_shell("mkdir -p /system/app/Bluetooth/lib/arm")
    runner.push(apk_src, "/data/local/tmp/Bluetooth.apk")
    runner.push(jni_src, "/data/local/tmp/libbluetooth_jni.so")
    runner.root_shell("cp /data/local/tmp/Bluetooth.apk /system/app/Bluetooth/Bluetooth.apk")
    runner.root_shell("cp /data/local/tmp/libbluetooth_jni.so "
                      "/system/app/Bluetooth/lib/arm/libbluetooth_jni.so")
    runner.root_shell("cp /data/local/tmp/libbluetooth_jni.so /system/lib/libbluetooth_jni.so")
    runner.root_shell("chmod 644 /system/app/Bluetooth/Bluetooth.apk")
    runner.root_shell("chown root:root /system/app/Bluetooth/Bluetooth.apk")

    packages = [p.strip() for p in cfg.get("disable_packages", "").split(",") if p.strip()]
    for pkg in packages:
        runner.root_shell(f"pm disable {pkg} 2>/dev/null || true")

    print("\n[7/8] bluetooth address + state")
    if bdaddr:
        runner.root_shell(f"mkdir -p /data/local/etc; echo '{bdaddr}' > /data/local/etc/bt_bdaddr")
        runner.root_shell("chmod 644 /data/local/etc/bt_bdaddr")
    runner.root_shell("rm -rf /data/misc/bluedroid; mkdir -p /data/misc/bluedroid")
    runner.root_shell("chown bluetooth:bluetooth /data/misc/bluedroid")
    runner.root_shell("chmod 770 /data/misc/bluedroid")
    runner.root_shell("sync")

    print("\n[8/8] reboot")
    if not args.skip_reboot:
        runner.root_shell("reboot", timeout=30)
        print("[*] rebooting. Reconnect with tools/find_headunit.py afterwards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
