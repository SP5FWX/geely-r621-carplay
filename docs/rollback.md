# 回滚手册

> **优先使用一键回滚**：`./rollback.sh --list` 查看备份内容，
> `./rollback.sh --apply` 执行复原。本文余下部分是等价的手工命令，
> 供脚本不可用（例如 PC 上只有 adb）时对照使用。

改造前必须完成本文第 1 节的备份。回滚目标：**恢复原车 Barrot/IVT 蓝牙栈**，
让原车蓝牙电话、音乐、方控恢复正常。

## 1. 必须备份的文件

```bash
adb shell su -c 'mkdir -p /data/local/aosp_bak'

# 原车蓝牙守护进程
adb shell su -c 'cp /system/bin/brlinkd /data/local/aosp_bak/brlinkd.orig'

# 原车 HAL
adb shell su -c 'cp /system/vendor/lib/hw/bluetooth.blueangel.so /data/local/aosp_bak/'

# 可能被覆盖的 AOSP 相关文件（如果已存在）
adb shell su -c 'cp /system/lib/hw/bluetooth.default.so       /data/local/aosp_bak/ 2>/dev/null'
adb shell su -c 'cp /system/lib/libbt-vendor.so               /data/local/aosp_bak/ 2>/dev/null'
adb shell su -c 'cp /system/app/Bluetooth/Bluetooth.apk       /data/local/aosp_bak/Bluetooth.apk.orig 2>/dev/null'

# DiPlay 应用与数据
adb shell su -c 'cp /system/app/DiPlay/DiPlay.apk /data/local/aosp_bak/DiPlay_orig 2>/dev/null'
adb shell su -c 'cp -r /data/data/com.shihab.diplay /data/local/aosp_bak/DiPlay_data_orig'
```

确认：

```bash
adb shell su -c 'ls -la /data/local/aosp_bak'
```

## 2. 回滚步骤

### 2.1 remount

```bash
adb shell su -c 'mount -o rw,remount /system'
```

### 2.2 恢复原车 brlinkd

```bash
adb shell su -c 'cp /data/local/aosp_bak/brlinkd.orig /system/bin/brlinkd'
adb shell su -c 'chmod 755 /system/bin/brlinkd'
adb shell su -c 'chown root:shell /system/bin/brlinkd'
```

### 2.3 移除 AOSP HAL 与 vendor 库

```bash
adb shell su -c 'rm -f /system/lib/hw/bluetooth.default.so'
adb shell su -c 'rm -f /system/lib/hw/bluetooth.mt6735.so'
adb shell su -c 'rm -f /system/vendor/lib/hw/bluetooth.default.so'
adb shell su -c 'rm -f /system/vendor/lib/hw/bluetooth.mt6735.so'
adb shell su -c 'rm -f /system/lib/libbt-vendor.so'
adb shell su -c 'rm -f /system/vendor/lib/libbt-vendor.so'
```

> 如果 `rm` 被 ROM 的 safe-delete 策略拦截，改用 `mv` 到备份区：
> `adb shell su -c 'mv /system/lib/hw/bluetooth.default.so /data/local/aosp_bak/'`

### 2.4 恢复原车蓝牙应用

```bash
for p in com.ivt.bt com.jsbd.btservice ecarx.bluetooth.service com.ecarx.btphone; do
  adb shell su -c "pm enable $p"
done
```

如果安装过 AOSP 的 `com.android.bluetooth`，可以保留（不会自动启动），
也可以禁用：

```bash
adb shell su -c 'pm disable com.android.bluetooth'
```

### 2.5 恢复 Bluedroid 状态目录权限

```bash
adb shell su -c 'rm -rf /data/misc/bluedroid'
adb shell su -c 'sync'
```

### 2.6 重启

```bash
adb shell su -c 'reboot'
```

## 3. 验证回滚成功

```bash
# 原车 brlinkd 应该在跑
adb shell su -c 'ps | grep brlinkd'

# 节点应恢复为 /dev/ivt_stpbt
adb shell su -c 'ls -la /dev/stpbt /dev/ivt_stpbt'

# 原车蓝牙日志应出现 HCI 收发
adb logcat -d | grep -E 'BARROT|bse_stack|bse_hfp' | tail -20
```

期望：

```
D/brlinkd: [BARROT] read(...), s_context.buffer=AT#HK<MAC>
D/bse_stack: [BARROT] [HCI][*Recv]/[*Send]
D/bse_hfp: [BARROT] Remote phone signal strength = 4
```

## 4. 恢复 DiPlay 到官方原版

```bash
adb shell su -c 'mount -o rw,remount /system'
adb shell su -c 'cp /data/local/aosp_bak/DiPlay_orig /system/app/DiPlay/DiPlay.apk'
adb shell su -c 'chmod 644 /system/app/DiPlay/DiPlay.apk'
adb shell su -c 'am force-stop com.shihab.diplay'
adb shell su -c 'rm -rf /data/data/com.shihab.diplay'
adb shell su -c 'cp -r /data/local/aosp_bak/DiPlay_data_orig /data/data/com.shihab.diplay'
adb shell su -c 'chown -R 10042:10042 /data/data/com.shihab.diplay'
adb shell su -c 'reboot'
```

## 5. 应急：车机无法启动

1. 尝试进入 recovery（车型按键组合不同，常见为音量+ + 电源长按）
2. 通过 `adb sideload` 刷回官方 OTA 包
3. 若只有 `/system` 被改，通常可用官方固件的 `system.img` 单独刷回

**不要**在没有官方固件的情况下随意格式化 `/data`。
