# 补丁二/三：蓝牙名称回退

## 现象

```
E/DiPlay: The head unit would not say what its Bluetooth is called
W/HOTSPOT/BRING_UP_FAILED
```

界面停在"正在连接…"，无线 CarPlay 无法建立。

## 根因

无线 CarPlay 的初始协商需要车机的 **radio name**（蓝牙名称）。
DiPlay 在吉利车型上通过 `VendorCarHop.c(Context)` 读取原车 IVT 蓝牙名。

换成 AOSP Bluedroid 后：

- 原车 IVT 接口不存在 → `VendorCarHop` 返回 `null`
- 但标准 `BluetoothAdapter.getName()` 是正常的（返回 `R621`）

DiPlay 没有回退路径，于是直接失败。

## 修改

在两处插入同一个回退：**hop 名称为空时，改用标准 API**。

### 1. `CarPlayController.smali` — `F()V`（`requireCarHopRadioName`）

```smali
# 在 CarBluetoothHops 读取之前插入
invoke-static {}, Landroid/bluetooth/BluetoothAdapter;->getDefaultAdapter()Landroid/bluetooth/BluetoothAdapter;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
invoke-virtual {v0}, Landroid/bluetooth/BluetoothAdapter;->getName()Ljava/lang/String;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
return-void
:cond_adapter_name_empty
```

该方法只做"确保名称存在"，拿到名字即可 `return-void`。

### 2. `WirelessIdentityResolver.smali` — `b(...)`（`resolveRadioName`）

```smali
# 在调用 a(WirelessBluetoothHop) 之前插入
invoke-static {}, Landroid/bluetooth/BluetoothAdapter;->getDefaultAdapter()Landroid/bluetooth/BluetoothAdapter;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
invoke-virtual {v0}, Landroid/bluetooth/BluetoothAdapter;->getName()Ljava/lang/String;
move-result-object v0
if-eqz v0, :cond_adapter_name_empty
return-object v0
:cond_adapter_name_empty
```

该方法返回 `String`，所以是 `return-object`。

## 为什么不用 `getAddress()`

`BluetoothAdapter.getAddress()` 在 Android 6.0+ 恒返回
`02:00:00:00:00:00`，而且 CarPlay 协商要的是名称不是地址。
只用 `getName()`。

## 验证

```bash
adb shell dumpsys bluetooth_manager | grep -i name
adb logcat -d | grep -iE 'radio.?name|HOTSPOT'
```

DiPlay 界面应越过"车机没有告诉我们它的蓝牙叫什么"这一步，
进入热点/网络协商。

## 失败时的排查

如果仍然报同样的错：

1. 确认 AOSP 蓝牙已开启：`dumpsys bluetooth_manager | grep state` → `12`
2. 确认 `BluetoothAdapter.getName()` 非空：

   ```bash
   adb shell settings get global bluetooth_name
   ```

3. 确认补丁真的写进了 APK：

   ```bash
   apktool d DiPlay_signed.apk -o check
   grep -n "cond_adapter_name_empty" \
     check/smali/com/shilapi/xcertplay/orchestration/*.smali
   ```
