# HAL 层

本目录包含让 AOSP 5.1 Bluedroid 驱动 MT6620 所需的两样东西：

1. **`bt_vendor_mtk.c`** — vendor 库源码，实现 Android 5.1 的
   `BLUETOOTH_VENDOR_LIB_INTERFACE` 对象。
2. **`patch_hal.py`** — 对 AOSP `bluetooth.default.so` 做 2 字节补丁，
   强制调用 `bte_main_enable()`。

## 编译

```bash
./build.sh /usr/bin/arm-linux-gnueabi-gcc
```

产物 `build/libbt-vendor.so`。脚本会自动校验：

- `BLUETOOTH_VENDOR_LIB_INTERFACE` 是 `OBJECT GLOBAL` 符号
- 同时存在 `HASH` 与 `GNU_HASH` 动态段

任一不满足直接失败——这两个问题在车机上表现为"库加载了但没反应"，
不校验会浪费大量时间。

### 烘焙默认蓝牙地址（可选）

```bash
BT_BDADDR_DEFAULT=AA:BB:CC:DD:EE:FF ./build.sh
```

运行时优先读 `/data/local/etc/bt_bdaddr`，文件不存在才用编译期地址。

## HAL 补丁

```bash
python patch_hal.py stock/bt_default.so build/bluetooth.default.so
```

| 项 | 值 |
|---|---|
| 适用版本 | AOSP 5.1 LMY48M (Nexus 5 / hammerhead) |
| 文件偏移 | `0x4999A` |
| 原始字节 | `44 B1`（`cbz r4, +0x10`） |
| 补丁后 | `08 E0`（`b +0x10`） |
| 作用 | 跳过 `btif_core_state` 判断，无条件执行 `bte_main_enable()` |

不同 ROM 的偏移不同。脚本检测到原始字节不匹配会拒绝执行并提示你
自行定位——这是刻意设计，盲打二进制会直接让车机蓝牙变砖。

## UART 节点

默认依次尝试：

```
/dev/stpbt
/dev/ttyMT0
/dev/ttyMT1
/dev/ttyMT2
```

非 MT6620 平台请修改 `g_devs[]` 后重新编译。

## 权限

```bash
chmod 644 /system/lib/libbt-vendor.so
chmod 666 /dev/stpbt
```

`brlinkd` 占位脚本会在开机后反复 `chmod 666 /dev/stpbt`，因为
`wmt_loader` 可能重建该节点。
