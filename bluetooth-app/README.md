# AOSP Bluetooth 应用

## 为什么要换这个 APK

DiPlay 依赖标准 Android 蓝牙服务。原车 ROM 的 `com.android.bluetooth`
要么不存在，要么是定制版（`sharedUserId` 被改掉）。要让它工作，必须满足：

| 条件 | 原因 |
|---|---|
| `android:sharedUserId="android.uid.bluetooth"` | 进程必须以 UID 1002 运行 |
| `android:persistent="true"` | 保证开机即拉起、常驻，否则拿不到系统 UID |
| platform 签名 | `framework-res.apk` 签名一致才能获得系统权限 |
| 装入 `/system/app/Bluetooth/` | 系统应用路径 |
| 配套 `libbluetooth_jni.so` | JNI 必须与 APK 同源 |

## 一个真实的坑

只做 platform 签名、**不加 `persistent`** 时，配对进行到最后一步会崩溃：

```
java.lang.SecurityException: Permission Denial: not allowed to send broadcast
android.bluetooth.device.action.BOND_STATE_CHANGED
from uid=10041
```

`10041` 就是"platform 签名但普通 UID"的典型表现。此时蓝牙进程被杀，
用户看到的现象是"一配对蓝牙就自动关闭"。

加上 `persistent` 后：

```bash
adb shell dumpsys package com.android.bluetooth | grep -E 'userId|flags'
# userId=1002
# flags=[ SYSTEM HAS_CODE PERSISTENT ALLOW_CLEAR_USER_DATA ALLOW_BACKUP ]
```

配对广播正常发出，绑定状态从 `BOND_BONDING(11)` 走到 `BOND_BONDED(12)`。

## 步骤

```bash
# 1. 从 AOSP 5.1 (LMY48M) 镜像中取出 Bluetooth.apk 与 libbluetooth_jni.so
#    本项目不分发这些文件

# 2. 反编译
apktool d Bluetooth.apk -o bt

# 3. 注入 persistent
python bluetooth-app/patch_manifest.py bt

# 4. 回编译 + platform 签名
apktool b bt -o Bluetooth_unsigned.apk
apksigner sign --key platform.pk8 --cert platform.x509.pem \
    --out Bluetooth_signed.apk Bluetooth_unsigned.apk

# 5. 部署
adb shell su -c 'mount -o rw,remount /system'
adb push Bluetooth_signed.apk /system/app/Bluetooth/Bluetooth.apk
adb push libbluetooth_jni.so /system/app/Bluetooth/lib/arm/libbluetooth_jni.so
adb push libbluetooth_jni.so /system/lib/libbluetooth_jni.so
adb shell su -c 'chmod 644 /system/app/Bluetooth/Bluetooth.apk'
adb shell su -c 'chown root:root /system/app/Bluetooth/Bluetooth.apk'

# 6. UID 变更后必须清数据（否则 UID 不会变成 1002）
adb shell su -c 'pm uninstall com.android.bluetooth'
adb shell su -c 'rm -rf /data/data/com.android.bluetooth'
adb shell su -c 'reboot'
```

## 关于 Odex

AOSP 镜像里的 `Bluetooth.odex` 不能直接放进 APK。需要先用
`baksmali` / `smali` 或 `dex2oat` 的产物还原成 `classes.dex`，
或者干脆用带 `classes.dex` 的 deodex 版本。

本项目脚本只处理 manifest，不涉及 dex 转换。

## 验证

```bash
adb shell dumpsys bluetooth_manager | grep -iE 'state|enabled'
# state: 12  (STATE_ON)

adb shell ps | grep com.android.bluetooth
# 进程存在且 uid=1002

adb logcat -d | grep -E 'Bond State Change Intent|bond_state_changed'
# OldState: 11 NewState: 12
```
