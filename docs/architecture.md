# 架构：为什么必须替换蓝牙栈

## 1. 车机原生结构

R621 的 ROM 里同时存在**两套互不相干的蓝牙主机栈**。

### A 栈 · Barrot / IVT（出厂默认，原车功能在用）

```
brlinkd (pid 301)
 ├── libbt_platform.so
 │     └── dlopen libbluetoothdrvbarrot.so
 │           └── libbluetoothbarrot_mtk.so
 │                 └── libnvram.so
 └── libbrlink.so          HCI / L2CAP / RFCOMM / OBEX / HFP / A2DP / AVRCP / PBAP / MAP
```

特征：

- 设备节点是 **`/dev/ivt_stpbt`**（`brlinkd` 启动时会把 `/dev/stpbt` 改名过去）
- 上电走 `rfkill` + `upio_set_bluetooth_power`
- 固件配置：`fw_config send write bd_addr baud 921600`
- 只服务原车包：`com.ivt.bt`、`com.jsbd.btservice`、
  `ecarx.bluetooth.service`、`com.ecarx.btphone`
- **不注册 Android 的 `BluetoothAdapter` 服务**，第三方 App 完全看不到它

### B 栈 · MTK Bluedroid（存在但未接回）

```
bluetooth.blueangel.so (BTIF_CORE)
 ├── libbtsession.so
 │     └── libextsys.so
 ├── libbtcust.so / libbtcusttable.so / libbtstd.so
 └── libmtk_drvb.so / libcustom_prop.so
```

关键事实（逆向结论）：

1. 它**不链接** `libbt_platform.so`，也不打开任何 UART 节点
   （全库搜不到 `/dev/stpbt`、`/dev/ivt_stpbt`、`ttyMT`）
2. 它使用 MTK 私有 IPC：`bt_session_connect` / `bt_session_write`，
   socket 组名 **`bt.session.default`**
3. 它是**客户端**——只导入 `bt_session_connect`，不导入 `bt_session_setup`
4. 上电消息 `btmtk_gap_power_on` 发出后，等待 `MSG_ID_BT_POWERON_CNF`，
   但 ROM 里找不到对应的服务端进程
5. `libbt_platform.so` **不导出** `bt_vendor_get_interface`，
   不能直接冒充 AOSP 的 `libbt-vendor.so`

**结论**：B 栈是一条断头路——它等一个永远不存在的对端进程。

## 2. 为什么选 AOSP Bluedroid

| 方案 | 可行性 | 代价 |
|---|---|---|
| 让原车 IVT 栈暴露 `BluetoothAdapter` | ❌ 闭源，无 HAL 接口 | 不可行 |
| 补上 `bt.session.default` 服务端 | ❌ ROM 中不存在该组件 | 需要重写传输层 |
| **替换为 AOSP 5.1 Bluedroid + 自写 vendor 库** | ✅ 已验证 | 原车蓝牙功能失效，可回滚 |
| USB 蓝牙 dongle + HCI 转发 | ⚠️ 可行但笨重 | 占用 USB，CarPlay 冲突 |

AOSP 5.1 的 HAL ABI 正好与 Android 5.1 匹配，且 `bluetooth.default.so`
只需要一个实现 `BLUETOOTH_VENDOR_LIB_INTERFACE` 的 vendor 库即可驱动
任意 H4 串口芯片——这正是 MT6620 的形态。

## 3. 改造后的数据流

```
DiPlay
  └─ BluetoothAdapter.enable()
       └─ BluetoothManagerService (framework)
            └─ com.android.bluetooth (UID 1002, persistent)
                 └─ libbluetooth_jni.so
                      └─ bluetooth.default.so  [AOSP LMY48M + 2 字节补丁]
                           ├─ bte_main_enable()  → GKI_create_task(BTU)
                           └─ dlopen("libbt-vendor.so")
                                └─ BLUETOOTH_VENDOR_LIB_INTERFACE
                                     ├─ USERIAL_OPEN → /dev/stpbt (fd ×4)
                                     ├─ HCI 0xFC1A  → 写入本机 BD_ADDR
                                     └─ FW_CFG      → 回调 fwcfg_cb
```

## 4. 分区布局变化

| 路径 | 改造前 | 改造后 |
|---|---|---|
| `/system/lib/hw/bluetooth.default.so` | （不存在或原厂桩） | AOSP 5.1 + 2 字节补丁 |
| `/system/vendor/lib/hw/bluetooth.default.so` | 同上 | 同上（副本） |
| `/system/lib/libbt-vendor.so` | 原厂 | 本项目编译产物 |
| `/system/vendor/lib/libbt-vendor.so` | 原厂 | 同上（副本） |
| `/system/app/Bluetooth/Bluetooth.apk` | 车机定制版 | AOSP + `persistent` + platform 签名 |
| `/system/bin/brlinkd` | 原车守护进程 | 占位脚本（保持 `/dev/stpbt` 权限、守护 adbd） |
| `/dev/ivt_stpbt` | 原车节点 | 改回 `/dev/stpbt` 供 AOSP 使用 |

原车文件全部备份在 `/data/local/aosp_bak/`。

## 5. 网络拓扑要求

无线 CarPlay 依赖 Bonjour/mDNS 与 AirPlay 的二层发现：

```
✅ 正确：iPhone ──Wi-Fi── 车机热点（同一二层网络）
✅ 正确：iPhone ──Wi-Fi── 家用路由器 ──Wi-Fi── 车机
❌ 错误：iPhone ──热点── 手机 ──热点── 车机（双层 NAT，mDNS 不通）
```

DiPlay 的 `WirelessHotspotMode` 对应两种正确拓扑：

| 枚举 | 含义 |
|---|---|
| `MANUAL` | 车机自己开热点，iPhone 连车机 |
| `EXISTING_WIFI` | 车机与 iPhone 连同一个外部 Wi-Fi |
| `LOCAL_ONLY_HOTSPOT` | 仅本地热点（无外网） |
