# 故障排查

按"现象 → 根因 → 处置"组织。日志过滤：

```bash
adb logcat -v time | grep -iE 'bluetooth|bt-|bt_|HOTSPOT|PAIRING|DiPlay|bluedroid'
```

---

## A. 部署与连接

### A1. `adb connect` 一直 `offline`

**根因**：`adb root` 会重启 adbd，旧连接句柄失效；或车机在多个 Wi-Fi 间切换。

**处置**：

```bash
adb kill-server
adb start-server
adb connect <ip>:5555
# 仍 offline 时，等 10–20 秒再试；不要连续 disconnect/connect
```

若车机刚从"热点模式"切回 STA 模式，IP 会变，重新扫描：

```bash
python tools/find_headunit.py
```

### A2. `su -c "长命令"` 报 `exec failed ... No such file or directory`

**根因**：部分车机的 `su` 把 `-c` 后整串当作可执行文件名，不经过 shell。

**处置**：显式套一层 shell：

```bash
adb shell "su 0 sh -c 'cat /data/data/.../xcertplay_airplay.xml'"
```

### A3. 车机没有 `sed` / `head` / `grep -A`

**根因**：Android 5.1 的 toybox 极简。

**处置**：不要依赖这些工具。用 `adb pull` 拉到 PC 改完再 `push`，
或用 `python` 在 PC 侧处理。

### A4. `adb push` 报路径不存在（Windows）

**根因**：Git Bash 的 MSYS 路径转换把 `/data/local/tmp/x` 转成了 `C:/.../data/...`。

**处置**：

```bash
export MSYS_NO_PATHCONV=1
```

---

## B. 蓝牙栈启动

### B1. `unable to find symbol BLUETOOTH_VENDOR_LIB_INTERFACE`

vendor 库没有导出全局对象。检查：

```bash
readelf -sW libbt-vendor.so | grep BLUETOOTH_VENDOR_LIB_INTERFACE
```

必须是 `OBJECT GLOBAL DEFAULT`，不能是 `FUNC`。
见 [bluedroid.md §1](bluedroid.md)。

### B2. vendor 库"加载了但符号找不到" / `dlopen` 静默失败

缺少 SysV hash。检查：

```bash
readelf -d libbt-vendor.so | grep HASH
```

只有 `GNU_HASH` 不够，必须同时有 `HASH`。重新编译时加
`-Wl,--hash-style=both`。

### B3. `preload_wait_timeout`

`BT_VND_OP_FW_CFG` 没有回调 `fwcfg_cb`。见 [bluedroid.md §3](bluedroid.md)。

### B4. 蓝牙 5 秒后自动关闭，native 层无日志

HAL 的 `btif_core_state` 分支问题，需要 2 字节补丁：

```bash
python hal/patch_hal.py stock/bt_default.so out/bluetooth.default.so
```

### B5. 蓝牙地址与出厂记录不一致（常见为 MTK 默认值）

`0xFC1A` 没发出去，或 `/data/local/etc/bt_bdaddr` 格式不对。
格式必须是 `AA:BB:CC:DD:EE:FF`（大写，冒号分隔），文件权限 `644`。

### B6. 蓝牙打开后立刻关闭，日志有 `SecurityException ... BOND_STATE_CHANGED`

APK 没有以 UID 1002 运行。检查：

```bash
adb shell dumpsys package com.android.bluetooth | grep -E 'userId|flags'
```

需要 `userId=1002` 且 `flags` 含 `PERSISTENT`。见 [bluedroid.md §7](bluedroid.md)。

若改过 `sharedUserId`，必须卸载重装并清理数据目录，否则 UID 不会变。

---

## C. 配对

### C1. 配对码弹窗一闪而过 / 提示已过期

配对码有效期很短。用自动化点击可以稳定通过：

```bash
adb shell uiautomator dump /sdcard/ui.xml
adb shell cat /sdcard/ui.xml    # 找 "配对" 按钮的 bounds
adb shell input tap <x> <y>
```

或写一个轮询脚本，监听 `蓝牙配对请求` 窗口出现即点击。

### C2. 配对成功但 DiPlay 看不到设备

`BOND_STATE_CHANGED` 没发出去（见 B6），或 DiPlay 缓存了旧状态。
`am force-stop` 后重开。

### C3. 配对后车机蓝牙自动关闭

同上，B6。这是本项目最典型的坑。

---

## D. 无线 CarPlay

### D1. `W/HOTSPOT/BRING_UP_FAILED`

三种可能：

1. 蓝牙名读不到 → 检查补丁二/三是否生效
2. 热点没真正开启 → 在系统设置里确认 AP 状态
3. 模式被强制降级 → 检查 `wireless_hotspot_mode` 是否被改回 `MANUAL`

### D2. `W/HOTSPOT/EXISTING_WIFI_CREDENTIALS_MISSING`

写 `existing_wifi_ssid` / `existing_wifi_passphrase`，
或写 `existing_wifi_networks` JSON。写完 `am force-stop` 再启动。

### D3. 一直"正在连接…"，会话建立不了

**先确认网络拓扑**：

```
iPhone 和车机必须在同一二层网络
```

- iPhone 连车机热点 ✅
- iPhone 和车机连同一个路由器 ✅
- iPhone → 手机热点 → 车机 ❌（双层 NAT，mDNS/Bonjour 不通）

其次确认：

```bash
adb shell "ip addr show wlan0 | grep inet"     # 车机 IP
adb shell "dumpsys wifi | grep -i 'ap state'"  # 热点状态
```

### D4. 热点一开，ADB 就断

正常。`wlan0` 从 STA 切到 AP 模式，IP 变成 `192.168.43.1`，
PC 不在该网段自然连不上。测试期间用 USB ADB，或让 PC 连车机热点后
`adb connect 192.168.43.1:5555`。

### D5. 连接成功但画面黑屏/卡顿

- 2.4GHz 信道拥挤 → 换 5GHz 或改信道
- 车机 CPU 负载高（MT6735 较老）→ 关闭其他应用
- DiPlay 显示参数不匹配 → 在 DiPlay 设置里调分辨率/帧率

---

## E. 回滚相关

### E1. 改完蓝牙后原车蓝牙电话不能用了

预期行为。原车 App 依赖 IVT 栈，回滚即可。见 [rollback.md](rollback.md)。

### E2. 车机变砖 / 无法开机

如果只是 `/system` 文件被替换，通常可以通过 recovery 或
`adb sideload` 恢复。本项目所有脚本在写入前都会备份到
`/data/local/aosp_bak/`，请优先用备份恢复。
