#!/usr/bin/env python3
"""Fail if the working tree contains secrets or personal identifiers.

Checks:
    1. private key material and signing files
    2. real-looking Bluetooth MAC addresses (allowlist for placeholders)
    3. DiPlay MFi assets
    4. non-placeholder Wi-Fi passphrases in tracked text files
    5. absolute home paths that leak a username

Run from the repository root before committing:

    python tools/check_secrets.py

Exit code 1 means something must be removed before publishing.

License: Apache-2.0
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ALLOWED_MAC = {
    "aa:bb:cc:dd:ee:ff",
    "00:00:00:00:00:00",
    "ff:ff:ff:ff:ff:ff",
    "02:00:00:00:00:00",
}

BANNED_SUFFIXES = {
    ".pk8", ".pem", ".keystore", ".jks", ".p12", ".pfx",
    ".apk", ".so", ".odex", ".img", ".zip", ".jar",
}

BANNED_NAMES = {
    "identity.pk8", "certificate.p7b",
}

PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("MAC address", re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")),
    ("windows user path", re.compile(r"C:\\\\?Users\\\\?[^\\\\/\s]+", re.I)),
    ("home path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")),
]

PASSPHRASE_HINT = re.compile(
    r"(?i)(passphrase|password|psk|keyMaterial)\s*[=:>\"']\s*([^\s\"'<>]{4,})"
)

# Values that are obviously placeholders.
PLACEHOLDER = re.compile(
    r"(?i)^(your|example|changeme|<|\.\.\.|xxx|placeholder|password|passphrase|"
    r"12345678|88888888|\*+$)"
)


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True,
                             text=True, check=True).stdout
        return [Path(p) for p in out.splitlines() if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in Path(".").rglob("*") if p.is_file() and ".git" not in p.parts]


def main() -> int:
    problems: list[str] = []

    for path in tracked_files():
        if path.suffix.lower() in BANNED_SUFFIXES:
            problems.append(f"{path}: banned binary/secret file type")
            continue
        if path.name in BANNED_NAMES:
            problems.append(f"{path}: DiPlay MFi asset")
            continue
        if path.stat().st_size > 2_000_000:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                hit = match.group(0)
                if label == "MAC address" and hit.lower() in ALLOWED_MAC:
                    continue
                problems.append(f"{path}: {label}: {hit}")

        for match in PASSPHRASE_HINT.finditer(text):
            value = match.group(2)
            if not PLACEHOLDER.match(value):
                problems.append(f"{path}: possible credential: {match.group(1)}={value}")

    if problems:
        print("Secrets / identifiers found:\n", file=sys.stderr)
        for item in problems:
            print("  - " + item, file=sys.stderr)
        print("\nRemove or replace with placeholders before pushing.", file=sys.stderr)
        return 1

    print("[✓] no secrets detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
