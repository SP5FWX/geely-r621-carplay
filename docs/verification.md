# 可复现性验证

本项目的每一处二进制/字节码改动，都应当能从公开材料 + 本文步骤
重现出与实机完全一致的结果。以下是 2026-10 在 R621 上的实测记录。

## 1. HAL 补丁

| 项 | 值 |
|---|---|
| 输入 | AOSP 5.1 LMY48M `bt_default.so`（1317416 字节） |
| 输入 SHA-256 | `1c1b99d26b66402cda947513d506b7c38ed5084ada8f134dbca5682f92d4df29` |
| 偏移 | `0x4999A` |
| 原始 → 补丁 | `44 B1` → `08 E0` |
| 输出 MD5 | `13fe4384e1a8ed50ed55b8048cee6a0f` |

```bash
python hal/patch_hal.py stock/bt_default.so out/bluetooth.default.so
# [*] bytes @0x4999A: 44 b1
# [+] patched: 44 b1 -> 08 e0
```

实机运行的就是这个输出。

## 2. vendor 库

```bash
cd hal && ./build.sh /usr/bin/arm-linux-gnueabi-gcc
```

| 项 | 值 |
|---|---|
| 编译器 | arm-linux-gnueabi-gcc |
| 产物大小 | 7764 字节（-O2，含日志） |
| 导出符号 | `BLUETOOTH_VENDOR_LIB_INTERFACE`，16 字节 OBJECT GLOBAL |
| 动态段 | 同时含 `HASH` 与 `GNU_HASH` |

## 3. DiPlay smali 补丁

以 DiPlay Legacy Geely V044 的 `apktool d` 输出为基线，应用
`diplay/patches/patches.json` 后，三个文件的 MD5 与实机安装包中的
smali 完全一致：

| 文件 | MD5 |
|---|---|
| `smali/com/shilapi/xcertplay/AirPlayPersistence.smali` | `a029cfb08e482b8bfd5007b3f8619583` |
| `smali/com/shilapi/xcertplay/orchestration/CarPlayController.smali` | `6921d95c6f88b77ff932933bdff133ab` |
| `smali/com/shilapi/xcertplay/orchestration/WirelessIdentityResolver.smali` | `7ace87e5162587d96b39e1714555b020` |

复现方法：

```bash
apktool d DiPlay.apk -o base
python diplay/apply_smali_patches.py base
md5sum base/smali/com/shilapi/xcertplay/AirPlayPersistence.smali
```

> 注意：脚本以 `newline=""` 读写，避免 Windows 下把 LF 改成 CRLF
> 导致 smali 文件哈希变化。这个细节曾让首次比对失败。

## 4. 实机状态验收

```bash
adb shell dumpsys bluetooth_manager | grep 'state:'
#   state: 12

adb shell dumpsys package com.android.bluetooth | grep -E 'userId|PERSISTENT'
#   userId=1002
#   flags=[ SYSTEM HAS_CODE PERSISTENT ... ]

adb logcat | grep 'Bond State Change Intent'
#   OldState: 11 NewState: 12
```

DiPlay 界面：

```
MFi 认证            ✓
热点就绪            ✓
蓝牙配对            ✓
网络接入            ✓
数据通道            无线 CarPlay 控制通道运行中
会话建立            ✓ → 车机屏幕出现 CarPlay 界面
```
