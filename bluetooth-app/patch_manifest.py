#!/usr/bin/env python3
"""Make com.android.bluetooth run as UID 1002 so it may send BOND_STATE_CHANGED.

Why this is needed
------------------
`android.bluetooth.device.action.BOND_STATE_CHANGED` is declared with
protectionLevel="signature" and AMS additionally requires the sender to be the
Bluetooth UID (1002). A platform-signed APK installed as a normal app still
gets a regular app UID (e.g. 10041) and crashes during pairing:

    SecurityException: Permission Denial: not allowed to send broadcast
    android.bluetooth.device.action.BOND_STATE_CHANGED from uid=10041

Adding android:persistent="true" makes the system start the process at boot
and keep it running, which is what makes the Bluetooth shared UID effective.

Usage:
    python patch_manifest.py path/to/apktool_project [--dry-run]

The script edits AndroidManifest.xml in place and does not sign anything.

License: Apache-2.0
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ATTR = 'android:persistent="true"'
SHARED_UID = 'android:sharedUserId="android.uid.bluetooth"'


def find_application_tag(xml: str) -> re.Match[str] | None:
    return re.search(r"<application\b[^>]*>", xml, re.S)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", help="apktool project directory")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = Path(args.project) / "AndroidManifest.xml"
    if not manifest.is_file():
        print(f"error: {manifest} not found (did you run apktool d?)", file=sys.stderr)
        return 2

    xml = manifest.read_text(encoding="utf-8")

    app = find_application_tag(xml)
    if not app:
        print("error: no <application> tag", file=sys.stderr)
        return 3

    tag = app.group(0)
    changed = []

    if "android:persistent" in tag:
        print("[=] android:persistent already present")
    else:
        new_tag = tag[:-1].rstrip() + " " + ATTR + ">"
        xml = xml[:app.start()] + new_tag + xml[app.end():]
        changed.append("added android:persistent")

    if "android.uid.bluetooth" in xml:
        print("[=] sharedUserId=android.uid.bluetooth present")
    else:
        print(
            "[!] sharedUserId=android.uid.bluetooth is missing.\n"
            "    This APK is probably not the AOSP Bluetooth app, or apktool\n"
            "    stripped it. The patch alone will not yield UID 1002.",
            file=sys.stderr,
        )

    if not changed:
        print("[✓] nothing to do")
        return 0

    if args.dry_run:
        print("[dry-run] would modify:", ", ".join(changed))
        return 0

    backup = manifest.with_suffix(".xml.bak")
    if not backup.exists():
        shutil.copy2(manifest, backup)
        print(f"[*] backup: {backup}")

    manifest.write_text(xml, encoding="utf-8")
    print("[+] " + ", ".join(changed))
    print(
        "\nNext:\n"
        "  apktool b <project> -o Bluetooth_unsigned.apk\n"
        "  apksigner sign --key platform.pk8 --cert platform.x509.pem \\\n"
        "      --out Bluetooth_signed.apk Bluetooth_unsigned.apk\n"
        "  adb push Bluetooth_signed.apk /system/app/Bluetooth/Bluetooth.apk\n"
        "  adb shell su -c 'pm uninstall com.android.bluetooth'   # 首次变更 UID 时必须\n"
        "  adb shell su -c 'rm -rf /data/data/com.android.bluetooth'\n"
        "  adb shell su -c 'reboot'\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
