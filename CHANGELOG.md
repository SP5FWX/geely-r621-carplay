# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `install.sh` — one-click installer: preflight → connect/root → backup →
  build → patch → deploy → reboot. Dry-run by default; `--apply` required.
  Also `--backup-only`, `--skip-build`, `--skip-reboot`, `--hal-so`,
  `--stock-so`, `--target`, `--bdaddr`.
- `rollback.sh` — one-click restore driven by `$BACKUP/manifest.txt`:
  puts every original back with its mode, deletes only files that had no
  original (after copying them into `$BACKUP/replaced/`), re-enables the stock
  Bluetooth packages, and optionally restores DiPlay (`--restore-diplay`).
  `--list` is read-only and safe to run at any time.
- Both scripts quote-escape every `su 0 sh -c '...'` payload. Without this,
  a path containing `'` truncated the command and produced an **empty backup
  that looked successful** (found during offline simulation).

### Changed

- Backup filenames now use a flat `_system_lib_hw_...orig` scheme, so
  `/system/lib/hw/bluetooth.default.so` and
  `/system/vendor/lib/hw/bluetooth.default.so` no longer collide.
- `manifest.txt` only records files that actually existed on the device;
  rollback no longer warns about entries it could never restore.

## [1.0.0] - 2026-10-25

### Added

- MT6620 vendor library source (`hal/bt_vendor_mtk.c`) implementing the
  Android 5.1 `BLUETOOTH_VENDOR_LIB_INTERFACE` ABI, including:
  - `fwcfg_cb` completion (prevents `preload_wait_timeout`)
  - single fd mapped to all four HCI channels on `USERIAL_OPEN`
  - MTK vendor command `0xFC1A` for local BD_ADDR configuration
- `hal/build.sh` cross-compile script with `--hash-style=both`
  (required by the Android 5.1 linker).
- `hal/patch_hal.py`: verified 2-byte patch of `btif_enable_bluetooth`
  (`cbz r4` → `b`) at file offset `0x4999A` for AOSP 5.1 LMY48M
  `bluetooth.default.so`.
- `bluetooth-app/patch_manifest.py`: adds `android:persistent="true"` so the
  Bluetooth process runs under UID 1002 and may send the protected
  `BOND_STATE_CHANGED` broadcast.
- DiPlay smali patches:
  - remove forced `EXISTING_WIFI` → `MANUAL` downgrade
  - fall back to `BluetoothAdapter.getName()` when the Geely hop interface
    returns null
- Deployment and diagnostics tooling: `tools/find_headunit.py`,
  `tools/deploy_hal.py`, `tools/doctor.py`.
- Documentation covering architecture, Bluedroid bring-up, DiPlay internals,
  troubleshooting, rollback, and legal/safety notes.

### Verified

- Bluetooth stack reaches `state: 12` (ON) on R621.
- iPhone pairs successfully; LinkKey persisted.
- DiPlay wireless session established and CarPlay displayed on the head unit.

[1.0.0]: https://github.com/SP5FWX/geely-r621-carplay/releases/tag/v1.0.0
