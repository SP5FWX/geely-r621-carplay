#!/usr/bin/env python3
"""Patch AOSP 5.1 (LMY48M) bt_default.so to always call bte_main_enable().

Background
----------
On some vendor ROMs the initial value of `btif_core_state` is non-zero, so
`btif_enable_bluetooth` takes the `cbz r4` branch and never calls
`bte_main_enable()`. Bluetooth then times out after 5 s with no native logs.

Disassembly (Nexus 5 LMY48M):

    0x49978  btif_enable_bluetooth
    ...
    0x49996  ldr  r4, [pc, #...]     ; btif_core_state
    0x4999A  44 B1                  ; cbz r4, +0x10   -> skip enable
    0x4999C  ...                     ; blx bte_main_enable

Replacing `44 B1` with `08 E0` (`b +0x10`) makes the call unconditional.

The script refuses to patch when the expected bytes are absent, because
offsets differ between builds.

Usage:
    python patch_hal.py stock/bt_default.so out/bluetooth.default.so
    python patch_hal.py --offset 0x4999A stock.so out.so

License: Apache-2.0
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

DEFAULT_OFFSET = 0x4999A
EXPECTED = b"\x44\xb1"          # cbz r4, +0x10
PATCHED = b"\x08\xe0"           # b   +0x10

# AOSP 5.1 LMY48M hammerhead bt_default.so, for a friendly sanity warning only.
KNOWN_SHA256_PREFIXES = ()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="stock bt_default.so")
    ap.add_argument("dst", help="output path")
    ap.add_argument("--offset", default=hex(DEFAULT_OFFSET),
                    help="file offset in hex (default: 0x4999A)")
    ap.add_argument("--force", action="store_true",
                    help="write even if the bytes already look patched")
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    if not src.is_file():
        print(f"error: not found: {src}", file=sys.stderr)
        return 2

    offset = int(args.offset, 16) if isinstance(args.offset, str) else args.offset
    data = bytearray(src.read_bytes())
    digest = sha256(src)
    print(f"[*] input : {src} ({len(data)} bytes)")
    print(f"[*] sha256: {digest}")

    if offset + len(EXPECTED) > len(data):
        print("error: offset beyond end of file", file=sys.stderr)
        return 3

    current = bytes(data[offset:offset + len(EXPECTED)])
    print(f"[*] bytes @0x{offset:X}: {current.hex(' ')}")

    if current == PATCHED and not args.force:
        print("[=] already patched; nothing to do")
    elif current == EXPECTED:
        data[offset:offset + len(EXPECTED)] = PATCHED
        print(f"[+] patched: {EXPECTED.hex(' ')} -> {PATCHED.hex(' ')}")
    else:
        print(
            "error: unexpected bytes. This binary is probably a different build.\n"
            "       Locate btif_enable_bluetooth in your own binary, find the\n"
            "       'cbz r4' immediately before the bte_main_enable call, and\n"
            "       pass its file offset with --offset.",
            file=sys.stderr,
        )
        return 4

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.resolve() != src.resolve():
        shutil.copy2(src, dst)
        with dst.open("r+b") as fh:
            fh.seek(offset)
            fh.write(PATCHED)
    else:
        with dst.open("r+b") as fh:
            fh.seek(offset)
            fh.write(PATCHED)

    out = bytearray(dst.read_bytes())
    ok = bytes(out[offset:offset + len(PATCHED)]) == PATCHED
    print(f"[*] output: {dst} sha256={sha256(dst)}")
    print("[✓] verification passed" if ok else "[!] verification FAILED")
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
