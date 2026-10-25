# 补丁一：解除 `EXISTING_WIFI` 强制降级

## 现象

把 `wireless_hotspot_mode` 设为 `EXISTING_WIFI` 后：

- 重启 DiPlay，值变回 `MANUAL`
- 界面提示"车机热点未开启"
- 日志：`W/HOTSPOT/BRING_UP_FAILED`

## 根因

吉利定制版 DiPlay 在读取配置时，把"与手机连同一 Wi-Fi"这个模式
当作不受支持，强制改回"车机自开热点"。

对应 `com/shilapi/xcertplay/AirPlayPersistence.smali` 的两个方法：

- `v(Context)` —— 读取模式
- `z(Context, WirelessHotspotMode)` —— 写入/规范化模式

原始字节码（简化）：

```smali
# mode == EXISTING_WIFI ?
if-ne v2, v3, :cond_4      # 不相等才跳过
# 落入这里 = 相等 → 在这里被改写成 MANUAL
```

`if-ne` = "not equal"，配合后面的赋值，实际语义是
"只要不是别的值就改" —— 分支条件与作者意图相反。

## 修改

```diff
-    if-ne v2, v3, :cond_4
+    if-eq v2, v3, :cond_4
```

```diff
-    if-ne p1, v0, :cond_1
+    if-eq p1, v0, :cond_1
```

把 `if-ne` 改成 `if-eq` 后，分支语义反转，`EXISTING_WIFI` 被保留。

## 验证

```bash
adb shell am force-stop com.shihab.diplay
adb shell su -c 'grep wireless_hotspot_mode \
  /data/data/com.shihab.diplay/shared_prefs/xcertplay_airplay.xml'
# <string name="wireless_hotspot_mode">EXISTING_WIFI</string>

adb shell am start -n com.shihab.diplay/com.shilapi.xcertplay.DiPlayActivity
# 再次读取，值不应被改写
```

## 注意

这个补丁只是"允许"该模式存在。是否真的能连上，还取决于：

- `existing_wifi_ssid` / `existing_wifi_passphrase` 是否正确
- iPhone 与车机是否在同一二层网络（不能有双层 NAT）
