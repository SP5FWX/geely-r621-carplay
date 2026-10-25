# Contributing

Thanks for taking the time to contribute.

## Before you start

This project modifies system partitions on a vehicle head unit. Changes that
look harmless on a desk can brick a car. If your change touches deployment
logic, it must include a rollback path and be tested on real hardware (or be
explicitly marked as untested in the pull request).

## Reporting issues

Use the bug report template and include:

- Head unit model, MCU/SoC, Android version, ROM build number
- Which step failed (deploy / pairing / hotspot / session)
- Relevant `logcat` lines (filter with `bluetooth|bt_|HOTSPOT|PAIRING|DiPlay`)
- Whether a rollback was performed afterwards

Never paste your Bluetooth MAC, Wi-Fi password, VIN, or signing keys into an
issue.

## Pull requests

1. Fork the repository and create a topic branch.
2. Keep changes focused: one logical change per PR.
3. Match the existing code style (C99, 4-space indent; Python: PEP 8).
4. Update `CHANGELOG.md` under `## [Unreleased]`.
5. If you add a binary patch, include:
   - the exact file offset,
   - the expected original bytes,
   - a checksum of the input binary,
   - a verification step in the script.
6. By submitting a PR you agree to license your contribution under
   Apache-2.0.

## Code of conduct

Be civil and technical. No harassment, no vendor bashing. Discussions about
circumventing DRM or redistributing proprietary software are out of scope.
