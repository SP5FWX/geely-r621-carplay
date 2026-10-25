# Security Policy

## Scope

This repository contains low-level tooling that writes to `/system` on an
Android head unit. Security issues we care about:

- Scripts that could destroy data without a backup or confirmation
- Command injection through deployment parameters
- Accidental inclusion of credentials, signing keys, or personal identifiers
- Unsafe file permissions on deployed binaries

## Reporting

Please **do not** open a public issue for a security problem.
Use GitHub's private vulnerability reporting ("Security" tab → "Report a
vulnerability") or contact the maintainer listed in the repository profile.

Include reproduction steps and the affected script. We aim to acknowledge
within 7 days.

## Out of scope

- Vulnerabilities in DiPlay, the head unit firmware, or AOSP itself — report
  those to the respective vendor.
- "Jailbreak"/root detection bypass requests.
- Questions about obtaining platform signing keys; we cannot help with that.

## Handling of secrets

Never commit:

- `platform.pk8`, `platform.x509.pem`, or any keystore
- DiPlay MFi assets (`identity.pk8`, `certificate.p7b`)
- Real Bluetooth MAC addresses, SSIDs, Wi-Fi passphrases
- ADB keys, SSH keys, or device serial numbers

A pre-commit check lives in `tools/check_secrets.py`; run it before pushing.
