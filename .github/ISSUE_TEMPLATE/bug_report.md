---
name: Bug report
about: Something doesn't work on your head unit
title: "[bug] "
labels: bug
---

## Environment

- Head unit model / MCU:
- SoC / Bluetooth chip:
- Android version / ROM build:
- DiPlay version:
- iPhone model / iOS version:
- Deployment method (script / manual):

## What happens

<!-- Describe the symptom. Attach a photo of the DiPlay screen if useful. -->

## Logs

<!--
Filter before pasting:
adb logcat -d | grep -iE 'bluetooth|bt-|bt_|HOTSPOT|PAIRING|DiPlay'
Remove MAC addresses, SSIDs, and VIN.
-->

```
<paste here>
```

## What you already tried

- [ ] rolled back
- [ ] re-deployed HAL
- [ ] re-signed and reinstalled Bluetooth.apk
- [ ] cleared /data/misc/bluedroid

## Rollback status

<!-- Did you restore the original IVT stack? Any lasting damage? -->
