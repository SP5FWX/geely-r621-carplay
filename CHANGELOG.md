# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
