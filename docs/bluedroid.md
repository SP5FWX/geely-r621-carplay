# Bluedroid 启动链路与 HAL 适配

本文记录把 AOSP 5.1 Bluedroid 接到 MT6620 上必须跨过的五个坑，
以及每个坑的判定依据。

## 1. HAL ABI：导出的是对象，不是函数

AOSP 5.1 的 `hardware/libhardware/include/hardware/bluetooth.h` 规定，
`bluetooth.default.so` 通过 `dlsym` 查找一个**全局对象**：

```c
// 正确：16 字节（32 位）对象
const bt_vendor_interface_t BLUETOOTH_VENDOR_LIB_INTERFACE = {
    sizeof(bt_vendor_interface_t),
    vnd_init,
    vnd_op,
    vnd_cleanup
};
```

```c
// 错误：某些第三方栈用这种形式，AOSP 5.1 不认
bt_vendor_interface_t *bt_vendor_get_interface(void);
```

失败表现：

```
E/Bluetooth: unable to find symbol BLUETOOTH_VENDOR_LIB_INTERFACE
```

### 回调表布局（5.1）

```c
typedef struct {
    size_t size;
    cfg_result_cb fwcfg_cb;
    cfg_result_cb scocfg_cb;
    cfg_result_cb lpm_cb;
    cfg_result_cb audio_state_cb;
    malloc_cb     alloc;
    mdealloc_cb   dealloc;
    cmd_xmit_cb   xmit_cb;
    cfg_result_cb epilog_cb;
} bt_vendor_callbacks_t;
```

`size` 字段必须等于结构体大小，否则框架会拒绝回调表。

## 2. linker：必须同时有 SysV hash 和 GNU hash

Android 5.1 的 linker 在 `dlopen` 时按 `DT_HASH` 查找符号。
只带 `DT_GNU_HASH` 的 so 会加载失败，且**没有明显报错**（表现为
vendor 库"似乎加载了但符号找不到"）。

```bash
arm-linux-gnueabi-gcc -shared -fPIC -O2 \
    -Wl,--hash-style=both \
    -o libbt-vendor.so bt_vendor_mtk.c
```

验证：

```bash
readelf -d libbt-vendor.so | grep -E 'HASH|GNU_HASH'
# 0x00000004 (HASH)      ...
# 0x6ffffef5 (GNU_HASH)  ...
```

## 3. FW_CFG 不回调 → `preload_wait_timeout`

Bluedroid 启动时进入 `preload` 阶段，等待 `fwcfg_cb(BT_VND_OP_RESULT_SUCCESS)`。
如果不回调，5 秒后：

```
E/Bluetooth: preload_wait_timeout
```

我们的芯片不需要下载固件（固件在 `/etc/firmware`，由 `brlinkd` 时代写入），
所以直接同步回调即可：

```c
case BT_VND_OP_FW_CFG:
    if (g_cb && g_cb->fwcfg_cb)
        g_cb->fwcfg_cb(BT_VND_OP_RESULT_SUCCESS);
    return 0;
```

## 4. USERIAL_OPEN：四个 channel 必须指向同一个 fd

AOSP 5.1 的 `userial` 会打开 4 条逻辑通道（CMD / ACL / SCO / EVT），
`p_data` 指向 `int fds[4]`。MT6620 是单串口 H4，四条通道共用同一 fd：

```c
int *fds = (int *)p;
for (ch = 0; ch < 4; ch++)
    fds[ch] = fd;          // 同一个 fd
```

如果只填 `fds[0]`，其余为 0/未初始化，ACL 数据会写进 stdin 或直接 EBADF。

## 5. 本机蓝牙地址：MTK 厂商命令 `0xFC1A`

不设置的话，芯片会报一个默认地址（实测是一个与出厂记录不一致的默认值），
导致配对信息与系统记录不一致、iPhone 反复重连。

MTK 私有 HCI 命令：

```
OGF = 0x3F (vendor)
OCF = 0x1A
opcode = 0xFC1A
参数 = 6 字节 BD_ADDR，小端序（LSB first）
```

完整 H4 帧（含 0x01 HCI Command 包类型）：

```c
unsigned char cmd[] = {
    0x01,                   // H4: HCI Command
    0x1A, 0xFC,             // opcode 0xFC1A (little-endian)
    0x06,                   // parameter length
    0xFF, 0xEE, 0xDD, 0xCC, 0xBB, 0xAA   // AA:BB:CC:DD:EE:FF, LSB first
};
write(fd, cmd, sizeof(cmd));
```

发送时机：`USERIAL_OPEN` 成功之后、HCI 复位之前。

> `bt_vendor_mtk.c` 从 `/data/local/etc/bt_bdaddr` 读取地址，格式 `AA:BB:CC:DD:EE:FF`。
> 文件不存在时保留芯片出厂地址。

## 6. HAL 的 2 字节补丁：强制走 `bte_main_enable`

### 现象

```
CURRENT_STATE=OFF, MESSAGE = USER_TURN_ON
Setting state to 11                    ← TURNING_ON
Entering PendingCommandState           ← 应调用 enableNative()
（5 秒内 native 层零日志）
CURRENT_STATE=PENDING, MESSAGE = START_TIMEOUT
Error enabling Bluetooth
Setting state to 10
```

`enableNative()` 返回了 true，但 BTU 任务从未创建。

### 逆向结论（AOSP 5.1 LMY48M，Nexus 5 `bt_default.so`）

| 符号 | 偏移 | 行为 |
|---|---|---|
| `btif_enable_bluetooth` | `0x49978` | 读 `btif_core_state`，`cbz` 跳过 `bte_main_enable` |
| `bte_main_boot_entry` | `0x45F10` | 只做 GKI_init / 加载配置，**不建 BTU** |
| `bte_main_enable` | `0x45F9C` | `BTE_Init` + `GKI_create_task(task_id=0 [BTU])` |
| `vendor_open` | `0xF1FC8` | `dlopen` + `dlsym(BLUETOOTH_VENDOR_LIB_INTERFACE)` |

车机定制 ROM 的 `btif_core_state` 初值不为 0，`cbz` 直接跳过 enable，
于是既不建 BTU，也不报错。

### 补丁

文件偏移 `0x4999A`，原始字节 `44 B1`（`cbz r4, +0x10`），
改为 `08 E0`（`b +0x10`，无条件跳转）：

```bash
python hal/patch_hal.py stock/bt_default.so out/bluetooth.default.so
```

脚本会校验原始字节，不匹配则拒绝打补丁——不同 ROM 偏移不同，不能盲打。

### 验证成功的日志特征

```
I/bt-btu: GKI_create_task task_id=0 [BTU] starting
I/bt-hci: BT_HC_HDR ...
I/Bluetooth: Setting state to 12        ← ON
```

## 7. `BOND_STATE_CHANGED` 与 UID 1002

配对完成时 `BondStateMachine` 会发送：

```
android.bluetooth.device.action.BOND_STATE_CHANGED
```

该广播在 `frameworks/base/core/res/AndroidManifest.xml` 中是
`protectionLevel="signature"`，且只有 **Bluetooth UID (1002)** 被允许发送。
AMS 的检查是 `checkComponentPermission(... , uid)`。

错误表现：

```
java.lang.SecurityException: Permission Denial:
not allowed to send broadcast android.bluetooth.device.action.BOND_STATE_CHANGED
from uid=10041
```

`10041` 说明 APK 以独立 `sharedUserId` 安装，拿到了普通应用 UID。
即使签名是 platform，也无法发送该广播。

解决：让 Bluetooth 进程以 **UID 1002** 运行。AOSP 的 `com.android.bluetooth`
在 `AndroidManifest.xml` 中声明 `android:sharedUserId="android.uid.bluetooth"`，
但仅仅这样还不够——进程必须由系统在开机时拉起，否则会被当成普通应用分配 UID。

在原 manifest 的 `<application>` 上加：

```xml
android:persistent="true"
```

然后 platform 签名。验证：

```bash
adb shell dumpsys package com.android.bluetooth | grep -E 'userId|flags'
# userId=1002
# flags=[ SYSTEM HAS_CODE PERSISTENT ALLOW_CLEAR_USER_DATA ALLOW_BACKUP ]
```

> 注意：`sharedUserId` 必须在**首次安装前**就存在，且新旧 APK 签名一致。
> 如果之前用别的 UID 装过，需要先 `pm uninstall` 并清理 `/data/data/com.android.bluetooth`。

## 8. 手动触发 enable（调试用）

```bash
adb shell su -c "service call bluetooth_manager 6 s16 'com.android.shell'"
adb shell dumpsys bluetooth_manager | grep -iE 'state|enabled'
```

`state: 12` 即 `STATE_ON`。
