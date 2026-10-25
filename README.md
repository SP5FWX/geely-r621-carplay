# Geely R621 · DiPlay 无线 CarPlay 修复方案

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Android%205.1%20%2F%20API%2022-green.svg)]()
[![Status](https://img.shields.io/badge/status-verified%20on%20vehicle-brightgreen.svg)]()

> 在**保留原车系统**的前提下，为吉利第四代帝豪 ECARX R621 车机接回标准 AOSP Bluedroid 蓝牙栈，
> 修复 DiPlay 的配对崩溃与无线建链失败，实现 **iPhone 无线 CarPlay**。

**已验证环境**：吉利第四代帝豪 · ECARX R621 · MT6735 · Android 5.1（API 22）· GKUI19 · iPhone（iOS 16+）
**验证结果**：蓝牙配对成功 → MFi 认证通过 → 热点就绪 → 无线 CarPlay 会话建立，车机屏幕正常投屏。

> ⚠️ 本项目涉及系统分区修改。请先完整阅读 [安全与合规说明](docs/safety.md) 与 [回滚手册](docs/rollback.md)。
> 所有操作均需自担风险。

---

## 这个项目解决什么问题

R621 车机出厂预装的是 **ECARX / Barrot(IVT) 私有蓝牙栈**（`brlinkd` + `libbt_platform.so`），
它只服务原车的 `com.ivt.bt` 等应用，**不导出标准 Android `BluetoothAdapter`**。

而第三方无线 CarPlay 应用 **DiPlay** 依赖标准 AOSP 蓝牙接口完成三件事：

1. 读取车机蓝牙名称（用于无线 CarPlay 身份协商）
2. 与 iPhone 完成标准蓝牙配对（写入 LinkKey）
3. 通过 `BluetoothAdapter` 判断已配对设备

原车栈不提供这些能力，因此 DiPlay 在 R621 上会出现：

| 现象 | 根因 |
|---|---|
| 提示"车机没有告诉我们它的蓝牙叫什么" | 读取原车 IVT 蓝牙名失败 |
| 配对瞬间蓝牙进程崩溃、蓝牙自动关闭 | `BOND_STATE_CHANGED` 是 signature 级受保护广播，非 Bluetooth UID 发送被 AMS 拒绝 |
| `W/HOTSPOT/BRING_UP_FAILED` | 热点模式被强制降级 / 蓝牙身份缺失导致流程中断 |
| `W/HOTSPOT/EXISTING_WIFI_CREDENTIALS_MISSING` | DiPlay 未保存目标 Wi-Fi 凭证 |

本项目的做法是：**把车机的蓝牙主机栈换成 AOSP 5.1 Bluedroid**，并为 MT6620 芯片补一个可用的
vendor 库，再对 DiPlay 做最小 smali 补丁。原车 IVT 栈完整备份、可随时回滚。

---

## 方案总览

```
┌─────────────────────────────────────────────────────────────┐
│  DiPlay (com.shihab.diplay)                                 │
│    └── 标准 Android BluetoothAdapter / WifiManager          │
├─────────────────────────────────────────────────────────────┤
│  framework (Android 5.1)                                    │
│    └── com.android.bluetooth  ← AOSP，platform 签名，persistent │
├─────────────────────────────────────────────────────────────┤
│  libbluetooth_jni.so  →  bluetooth.default.so (AOSP 5.1)    │
│                            └── dlopen libbt-vendor.so        │
│                                  └── /dev/stpbt (MT6620)     │
├─────────────────────────────────────────────────────────────┤
│  原车 Barrot/IVT 栈：brlinkd（已替换为占位脚本，可回滚）      │
└─────────────────────────────────────────────────────────────┘
```

四个组成部分：

| 组件 | 作用 | 位置 |
|---|---|---|
| `hal/` | MT6620 vendor 库源码 + 交叉编译脚本 + HAL 2 字节补丁 | `/system/lib/libbt-vendor.so`、`/system/lib/hw/bluetooth.default.so` |
| `bluetooth-app/` | AOSP Bluetooth APK 的 `persistent` 补丁与签名流程 | `/system/app/Bluetooth/Bluetooth.apk` |
| `diplay/` | DiPlay 的三处 smali 补丁（无线模式、蓝牙名回退） | 重新签名的 DiPlay APK |
| `tools/` | 车机发现、状态诊断、部署脚本 | 在 PC 上运行 |

---

## 一键安装 / 一键恢复

先准备配置（只需一次）：

```bash
cp config/example.properties config/local.properties
# 编辑 target / bdaddr / aosp_dir
```

然后：

```bash
./install.sh              # 预演：打印完整计划并做备份，不写 /system
./install.sh --apply      # 安装：备份 → 构建 → 打补丁 → 部署 → 重启

./rollback.sh --list      # 只读：看看备份里到底有什么
./rollback.sh --apply     # 一键回滚原车 Barrot/IVT 蓝牙栈
```

**设计原则（与 `tools/deploy_hal.py` 一致）**

- `install.sh` **默认是 dry-run**，必须显式 `--apply` 才会写设备；
- 每个将被覆盖的文件先落到 `$BACKUP/files/*.orig`，并登记 `manifest.txt`（路径+权限）；
- `rollback.sh` 只按清单复原；对"安装时本来不存在"的文件才删除，且删除前先
  拷一份到 `$BACKUP/replaced/` 保险库；
- 清单为空时 `rollback.sh` 会直接拒绝执行——没有备份就不做不可逆操作。

| 场景 | 命令 |
|---|---|
| 只做备份（改系统前先跑） | `./install.sh --backup-only` |
| 已有打好补丁的 HAL | `./install.sh --apply --hal-so bt_default_patched.so` |
| 现场构建 + 打补丁 | `./install.sh --apply --stock-so /path/to/aosp/bluetooth.default.so` |
| 不自动重启 | `./install.sh --apply --skip-reboot` |
| 连 DiPlay 一起还原 | `./rollback.sh --apply --restore-diplay` |
| 无人值守回滚 | `./rollback.sh --apply --yes` |

日志写到 `logs/install-*.log`、`logs/rollback-*.log`（已被 `.gitignore` 忽略）。
两个脚本都会把执行的每条 adb 命令打印出来，出问题按日志逐条对账即可。

> 需要说明：本项目**不打包任何二进制**，`install.sh` 只是把你自己的 AOSP 预编译件
> 和本机编译产物推送到你自己的车机上，因此仓库本身不含可分发的固件或厂商代码。

---

## 手动步骤（与一键脚本等价）

如果你更愿意逐步执行，或想先核对每一步的作用：

### 0. 前置条件

- 车机已 root，且能通过网络 ADB 连接（`adb connect <车机IP>:5555`）
- PC 具备：`adb`、Python 3.8+、`apktool`、`apksigner`、`arm-linux-gnueabi-gcc`
- 已获取 **AOSP 5.1 (LMY48M) 的 `bluetooth.default.so` 与 `Bluetooth.apk`**
  （本项目**不分发**这些二进制，请从 AOSP 官方镜像自行提取）
- **平台签名密钥**：车机 `framework-res.apk` 的签名证书必须与你的 platform key 一致
  （本项目**不提供任何签名密钥**）

### 1. 备份（必须）

```bash
adb shell su -c 'mkdir -p /data/local/aosp_bak'
adb shell su -c 'cp /system/bin/brlinkd /data/local/aosp_bak/brlinkd.orig'
adb shell su -c 'cp /system/vendor/lib/hw/bluetooth.blueangel.so /data/local/aosp_bak/'
adb shell su -c 'cp -r /data/data/com.shihab.diplay /data/local/aosp_bak/DiPlay_data_orig'
```

完整清单见 [回滚手册](docs/rollback.md)。

### 2. 编译 MT6620 vendor 库

```bash
cd hal
./build.sh /path/to/arm-linux-gnueabi-gcc
# 产物：build/libbt-vendor.so
```

> 关键点：Android 5.1 的 linker 同时要求 SysV `DT_HASH` 与 GNU hash，
> 必须加 `-Wl,--hash-style=both`，否则 `dlopen` 静默失败。

### 3. 给 AOSP HAL 打 2 字节补丁

```bash
python hal/patch_hal.py /path/to/stock/bt_default.so build/bluetooth.default.so
# Patched offset 0x4999A: 44 B1 -> 08 E0  (cbz r4 -> b)
```

这一步把 `btif_enable_bluetooth` 里的条件分支改成无条件跳转，强制走 `bte_main_enable()`，
否则车机定制 ROM 的 `btif_core_state` 初值会让 enable 直接返回而不建 BTU 任务。

### 4. 部署

```bash
python tools/deploy_hal.py --target 192.168.1.23:5555 --bdaddr AA:BB:CC:DD:EE:FF
```

脚本会依次：备份 → remount `/system` → 停 `brlinkd` → 安装 HAL/vendor/JNI →
安装 platform 签名的 Bluetooth APK → 禁用原车蓝牙包 → 清理 Bluedroid 状态 → 重启。

### 5. 修补 DiPlay

```bash
# 1) apktool 反编译
apktool d DiPlay.apk -o diplay_base
# 2) 应用补丁（细节见 diplay/README.md）
python diplay/apply_smali_patches.py diplay_base
# 3) 回编译 + platform 签名
apktool b diplay_base -o DiPlay_patched.apk
apksigner sign --key platform.pk8 --cert platform.x509.pem --out DiPlay_signed.apk DiPlay_patched.apk
```

### 6. 连接

1. 车机设置 → 便携式热点 → 打开（记下 SSID / 密码）
2. iPhone → Wi-Fi → 连接该热点
3. DiPlay → 模式选 **车载热点** → 点「无线连接」

---

## 目录结构

```
.
├── README.md
├── LICENSE                     Apache-2.0
├── NOTICE                      第三方组件归属声明
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── install.sh                  一键安装（默认 dry-run，--apply 才写设备）
├── rollback.sh                 一键回滚（按 manifest 复原）
├── docs/
│   ├── architecture.md         双蓝牙栈架构与选型分析
│   ├── bluedroid.md            Bluedroid 启动链路、HAL ABI、HCI 命令
│   ├── diplay.md               DiPlay 配置键、补丁原理、错误码
│   ├── troubleshooting.md      症状 → 根因 → 处置 对照表
│   ├── rollback.md             完整回滚手册
│   ├── verification.md         可复现性验证（哈希对照）
│   └── safety.md               法律、保修与操作风险
├── hal/
│   ├── bt_vendor_mtk.c         MT6620 vendor 库（可配置 BD_ADDR）
│   ├── build.sh                交叉编译脚本
│   ├── patch_hal.py            AOSP HAL 2 字节补丁工具
│   └── README.md
├── bluetooth-app/
│   ├── patch_manifest.py       注入 android:persistent="true"
│   └── README.md
├── diplay/
│   ├── apply_smali_patches.py  三处补丁的自动化脚本
│   ├── patches/                补丁前后对照（可手工应用）
│   └── README.md
├── tools/
│   ├── find_headunit.py        扫描局域网内的车机 ADB
│   ├── deploy_hal.py           一键部署（带备份）
│   └── doctor.py               状态自检
└── config/
    ├── example.properties      部署参数模板
    ├── example-prefs.xml       DiPlay 配置模板（占位符）
    └── example-wifi-profile.xml
```

---

## 兼容性

| 项目 | 已验证 | 说明 |
|---|---|---|
| 车型 | 吉利第四代帝豪 ECARX R621 | 其他 GKUI19 / MT6735 车机可能适用，需自行验证 |
| Android | 5.1 (API 22) | HAL ABI 与 5.0/5.1 一致；6.0+ 需改用新版 HAL 接口 |
| 蓝牙芯片 | MT6620 / MT6735 平台 | vendor 库按 `/dev/stpbt` 设计，其他芯片需改 `g_devs` |
| iPhone | iOS 16+ | 无线 CarPlay 需要 5GHz Wi-Fi 或 2.4GHz 干净信道 |
| DiPlay | Legacy Geely V044 / 0.2.x | 补丁基于该版本 smali，其他版本需重新定位锚点 |

---

## 已知限制

- 无线 CarPlay 对 Wi-Fi 质量敏感：**iPhone 与车机必须在同一二层网络**，中间不能有 NAT
  （"iPhone → 手机热点 → 车机" 这种双层 NAT 无法建立 Bonjour/AirPlay）
- 修改蓝牙栈后，原车蓝牙电话/音乐功能会失效（原车 App 依赖 IVT 栈）；回滚即可恢复
- 部分车机在热点开启时会切换 `wlan0` 为 AP 模式，导致无线 ADB 断开，属正常现象
- 不同 ROM 的 `bluetooth.default.so` 偏移不同，`patch_hal.py` 会校验目标字节后再打补丁

---

## 法律声明

- 本项目是**个人技术研究与互操作性（interoperability）项目**，**非官方项目**，与吉利汽车、
  ECARX、Apple、联发科（MediaTek）及 DiPlay 作者均**无任何隶属、授权或背书关系**。
- "Geely"、"CarPlay"、"DiPlay" 等名称仅用于**描述兼容对象**（nominal / descriptive use），
  相关商标归各自权利人所有。
- 本项目**不包含、不分发**任何第三方二进制、固件、APK、MFi 证书或签名密钥；
  `install.sh` 只对**你本人拥有**的设备、使用**你自行获取**的 AOSP 预编译件执行操作。
- 请在**你拥有所有权或已获授权**的车辆上使用。因修改系统分区导致的保修失效、功能异常或
  设备损坏，由操作者自行承担。
- 请勿将本项目用于**商业分发、收费改装或绕过付费服务**；此类用法不在本项目许可与
  免责范围之内，且可能触及当地法律（包括技术保护措施相关条款）。

## 免责声明

本项目仅供**个人车辆的技术研究与互操作目的**使用。修改系统分区可能导致车机变砖、失去保修、
影响原车功能。请务必先备份并确认可回滚。详见 [docs/safety.md](docs/safety.md)。

本项目**不包含**、也**不分发**：

- DiPlay 官方 APK 及其 MFi 证书/私钥
- 任何平台的签名密钥（`platform.pk8` / `platform.x509.pem`）
- AOSP 预编译二进制（请从官方渠道获取）

---

## 致谢

- AOSP Bluedroid / BlueZ 社区
- MTK MT6620 逆向资料的开源贡献者
- DiPlay 作者（本项目仅做互操作性修补，不分发其软件）

## License

[Apache-2.0](LICENSE)

---

## English summary

**Geely R621 (ECARX, MT6735, Android 5.1) — iPhone wireless CarPlay via DiPlay.**

The stock head unit ships a private Barrot/IVT Bluetooth stack that never
registers Android's `BluetoothAdapter`, so DiPlay cannot pair or negotiate a
wireless session. This project replaces that stack with AOSP 5.1 Bluedroid:

1. **HAL** — `bt_vendor_mtk.c` implements the Android 5.1
   `BLUETOOTH_VENDOR_LIB_INTERFACE` for the MT6620 UART, plus a verified
   2-byte patch (`0x4999A: 44 B1 -> 08 E0`) that forces `bte_main_enable()`.
2. **Framework app** — AOSP `com.android.bluetooth` with
   `android:persistent="true"`, platform-signed, so it runs as UID 1002 and
   may send the protected `BOND_STATE_CHANGED` broadcast.
3. **DiPlay patches** — three anchor-checked smali edits: stop forcing
   `EXISTING_WIFI` back to `MANUAL`, and fall back to
   `BluetoothAdapter.getName()` when the Geely hop returns null.
4. **Tooling** — one-click `install.sh` (dry-run by default) and
   `rollback.sh` (manifest-driven restore), plus head-unit discovery,
   backup-first deployment, health report and secret scan.

```bash
./install.sh --apply     # backup -> build -> patch -> deploy -> reboot
./rollback.sh --apply    # put the stock Barrot/IVT stack back
```

Verified end to end on a real vehicle: Bluetooth `state: 12`, iPhone pairing,
wireless CarPlay session established.

Everything here is Apache-2.0. No DiPlay binaries, MFi credentials, AOSP
prebuilts, or signing keys are redistributed.

See [`docs/architecture.md`](docs/architecture.md),
[`docs/bluedroid.md`](docs/bluedroid.md),
[`docs/diplay.md`](docs/diplay.md), and
[`docs/rollback.md`](docs/rollback.md).
