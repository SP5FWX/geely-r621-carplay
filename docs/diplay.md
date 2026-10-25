# DiPlay 侧修补

DiPlay（`com.shihab.diplay`）是闭源应用。本项目**不修改其业务逻辑**，只做三处
互操作性修补，使其在 AOSP 蓝牙栈下正常工作。

> 本项目不分发 DiPlay APK。你需要自备合法获取的安装包，并自行完成反编译与重签名。
> 重签名需要车机的 platform key，或先卸载系统签名校验（取决于 ROM）。

## 1. 配置存储

| 项 | 值 |
|---|---|
| 数据目录 | `/data/data/com.shihab.diplay/` |
| 配置文件 | `shared_prefs/xcertplay_airplay.xml` |
| UID | 10042（实例相关，以 `dumpsys package` 为准） |

关键键：

| 键 | 类型 | 取值 |
|---|---|---|
| `wireless_hotspot_mode` | string | `LOCAL_ONLY_HOTSPOT` / `MANUAL` / `EXISTING_WIFI`（枚举名，由 `Enum.name()` 写入） |
| `existing_wifi_ssid` | string | 目标 Wi-Fi SSID |
| `existing_wifi_passphrase` | string | 目标 Wi-Fi 密码 |
| `existing_wifi_networks` | string | JSON 数组，元素 `{"ssid": "...", "passphrase": "..."}` |
| `wireless_enabled` | boolean | 是否启用无线模式 |
| `mfi_target` | string | `LOCAL` 表示使用本地 MFi 身份 |

### 读取优先级

`AirPlayPersistence.getExistingWifiNetworks()` 的逻辑：

1. 先读 `existing_wifi_networks`，`JSONArray` 解析成功且非空 → 使用列表
2. 否则回退到 `existing_wifi_ssid` + `existing_wifi_passphrase`

因此写入时**两个都写**最稳妥。只写 flat key 也能工作，但某些版本会优先读列表。

### 直接改 prefs 的注意事项

SharedPreferences 会被进程缓存在内存中。修改文件后必须：

```bash
adb shell am force-stop com.shihab.diplay
# 写入文件，chown 到应用 UID，chmod 660
```

否则应用下次 `commit()` 会用内存中的旧值覆盖你的修改。

## 2. 补丁一：解除 `EXISTING_WIFI` 强制降级

### 现象

把模式设为 `EXISTING_WIFI` 后，重启应用又变回 `MANUAL`，
DiPlay 界面提示"车机热点未开启"。

### 根因

`AirPlayPersistence.smali` 的 `v(Context)` 与 `z(Context, WirelessHotspotMode)`
在读取配置时，只要检测到 `EXISTING_WIFI` 就强制改写为 `MANUAL`（吉利定制行为）。

原始 smali（两处）：

```smali
if-ne v2, v3, :cond_4        # if (mode != EXISTING_WIFI) skip
...
if-ne p1, v0, :cond_1
```

`if-ne` 的含义是"不相等则跳过"，配合后续的赋值语句，实际效果是
"只要不是别的值就改成 MANUAL"。

### 修改

```smali
if-eq v2, v3, :cond_4        # 相等时才跳过 → 保留 EXISTING_WIFI
...
if-eq p1, v0, :cond_1
```

即把 `if-ne` 改成 `if-eq`，让分支语义反转、保留用户选择。

## 3. 补丁二/三：蓝牙名称回退

### 现象

```
E/DiPlay: The head unit would not say what its Bluetooth is called
W/HOTSPOT/BRING_UP_FAILED
```

### 根因

吉利定制 ROM 里，DiPlay 通过 `VendorCarHop.c(Context)` 读取原车 IVT 蓝牙名。
换成 AOSP 栈后这个接口返回 `null`，无线身份协商拿不到 radio name，流程中断。

AOSP 的蓝牙名其实存在（`R621`），只是走了另一条路径。

### 修改点

**`CarPlayController.smali`** — 方法 `F()V`（`requireCarHopRadioName()`），
在 hop 读取失败的分支插入标准 API 回退：

```smali
invoke-static {}, Landroid/bluetooth/BluetoothAdapter;->getDefaultAdapter()Landroid/bluetooth/BluetoothAdapter;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
invoke-virtual {v0}, Landroid/bluetooth/BluetoothAdapter;->getName()Ljava/lang/String;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
return-void
:cond_adapter_name_empty
```

**`WirelessIdentityResolver.smali`** — 方法 `b(...)`（`resolveRadioName`），
在 `:cond_4` 之前插入同样的回退，返回 `String`：

```smali
invoke-static {}, Landroid/bluetooth/BluetoothAdapter;->getDefaultAdapter()Landroid/bluetooth/BluetoothAdapter;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
invoke-virtual {v0}, Landroid/bluetooth/BluetoothAdapter;->getName()Ljava/lang/String;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
return-object v0
:cond_adapter_name_empty
```

### ⚠️ 寄存器类型陷阱（务必阅读）

第一版补丁在回退里加了长度检查：

```smali
invoke-virtual {v0}, Ljava/lang/String;->length()I
move-result v1          # v1 被定义为 int
if-nez v1, :cond_xxx
return-object v0        # 但 v0 是 String
```

结果：

```
java.lang.VerifyError: Rejecting class CarPlayController
  (declared in ...DiPlay.apk)
```

原因：`v1` 在原方法中已被定义为 `String` 引用，这里复用为 `int`，
Dalvik 的 verifier 在方法入口做类型合并时判定冲突，整类被拒绝加载。

**规则**：

1. 插入 smali 前，先确认目标方法里每个寄存器已有的类型
2. 不要复用寄存器做类型转换；用 `move-object` / `move` 明确区分
3. 优先只在**方法尾部**追加逻辑，避开 verifier 的类型合并点
4. 只做 `if-eqz` 非空判断，不做需要新寄存器的运算

## 4. 错误码对照

| 日志 | 含义 | 处置 |
|---|---|---|
| `W/PAIRING/BRING_UP_FAILED` | 蓝牙配对链路建立失败 | 检查 HAL 是否 `state: 12`、是否已配对 |
| `W/HOTSPOT/BRING_UP_FAILED` | 热点或身份协商失败 | 检查蓝牙名称回退补丁、热点是否真的开了 |
| `W/HOTSPOT/EXISTING_WIFI_CREDENTIALS_MISSING` | 目标 Wi-Fi 没存密码 | 写 `existing_wifi_passphrase` |
| `EXISTING_WIFI` 模式反复变回 `MANUAL` | 被强制降级 | 补丁一 |

## 5. 应用补丁

```bash
apktool d DiPlay.apk -o base
python diplay/apply_smali_patches.py base --dry-run   # 先看匹配结果
python diplay/apply_smali_patches.py base
apktool b base -o DiPlay_unsigned.apk
apksigner sign --key platform.pk8 --cert platform.x509.pem \
    --out DiPlay_signed.apk DiPlay_unsigned.apk
```

脚本采用**锚点精确匹配**：找不到目标行就报错退出，不会盲目替换。
DiPlay 升级后 smali 偏移会变，需要重新核对 `patches/` 下的对照。

## 6. 装机验证

```bash
adb shell dumpsys package com.shihab.diplay | grep -E 'versionName|userId'
adb shell su -c 'cat /data/data/com.shihab.diplay/shared_prefs/xcertplay_airplay.xml' \
  | grep -E 'wireless_hotspot_mode|existing_wifi'
adb shell am start -n com.shihab.diplay/com.shilapi.xcertplay.DiPlayActivity
```

界面应显示：

```
已配对设备: <iPhone 名称>
这台设备可以用：通过 USB 连接 · 车载热点
```
