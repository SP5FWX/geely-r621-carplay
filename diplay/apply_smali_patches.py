#!/usr/bin/env python3
"""Apply the DiPlay interoperability patches to an apktool project.

The patch definitions live in patches/patches.json. Each patch is anchor-based
and count-checked: if the expected text does not appear exactly the expected
number of times, nothing is written and the script exits non-zero. This is
deliberate — a blind smali edit can produce a class that fails verification and
takes the whole app down with VerifyError.

Usage:
    apktool d DiPlay.apk -o base
    python apply_smali_patches.py base --dry-run
    python apply_smali_patches.py base
    apktool b base -o DiPlay_unsigned.apk

License: Apache-2.0
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PATCH_FILE = Path(__file__).with_name("patches") / "patches.json"


def method_body(text: str, header: str) -> tuple[int, int] | None:
    """Return (start, end) character offsets of a .method block, if present."""
    start = text.find(header)
    if start < 0:
        return None
    end = text.find("\n.end method", start)
    if end < 0:
        return None
    return start, end + len("\n.end method")


def read_text(path: Path) -> str:
    """Read without newline translation (smali files must keep LF on Windows)."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def apply_patch(root: Path, patch: dict, dry_run: bool) -> str:
    target = root / patch["file"]
    if not target.is_file():
        return f"MISSING  {patch['file']}"

    text = read_text(target)
    original = text
    expected = patch.get("count", 1)

    if patch["type"] == "replace":
        found = text.count(patch["search"])
        if found != expected:
            return (f"FAIL     {patch['id']}: found {found} occurrence(s), "
                    f"expected {expected}")
        text = text.replace(patch["search"], patch["replace"])
    elif patch["type"] == "insert_before":
        method = patch.get("method")
        if method:
            span = method_body(text, method)
            if not span:
                return f"FAIL     {patch['id']}: method not found: {method}"
            start, end = span
            body = text[start:end]
            found = body.count(patch["anchor"])
            if found != expected:
                return (f"FAIL     {patch['id']}: anchor found {found} time(s) "
                        f"in method, expected {expected}")
            body = body.replace(patch["anchor"], patch["insert"] + patch["anchor"], 1)
            text = text[:start] + body + text[end:]
        else:
            found = text.count(patch["anchor"])
            if found != expected:
                return (f"FAIL     {patch['id']}: anchor found {found} time(s), "
                        f"expected {expected}")
            text = text.replace(patch["anchor"], patch["insert"] + patch["anchor"], 1)
    else:
        return f"FAIL     {patch['id']}: unknown type {patch['type']!r}"

    if text == original:
        return f"SKIP     {patch['id']} (already applied)"

    if not dry_run:
        backup = target.with_suffix(target.suffix + ".orig")
        if not backup.exists():
            shutil.copy2(target, backup)
        write_text(target, text)

    return f"OK       {patch['id']}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", help="apktool project directory")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--spec", default=str(PATCH_FILE))
    args = ap.parse_args()

    root = Path(args.project)
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"error: patch spec not found: {spec_path}", file=sys.stderr)
        return 2
    if not (root / "AndroidManifest.xml").is_file():
        print(f"error: {root} does not look like an apktool project", file=sys.stderr)
        return 2

    spec = json.loads(read_text(spec_path))
    print(f"[*] target: {spec.get('target')}  patches: {len(spec['patches'])}")
    print(f"[*] project: {root}\n")

    failures = 0
    for patch in spec["patches"]:
        result = apply_patch(root, patch, args.dry_run)
        print(("  " + result))
        if result.startswith("FAIL"):
            failures += 1

    print()
    if failures:
        print(f"[!] {failures} patch(es) failed. No partial writes were made for "
              f"the failing patches; re-check the DiPlay version and anchors.",
              file=sys.stderr)
        return 1

    if args.dry_run:
        print("[✓] dry-run passed. Re-run without --dry-run to write.")
    else:
        print("[✓] all patches applied. Next: apktool b + apksigner sign.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
