# DiPlay 补丁

三处互操作性修补，定义在 [`patches/patches.json`](patches/patches.json)。

| 补丁 | 文件 | 作用 |
|---|---|---|
| `hotspot-mode-keep-existing-wifi-1/2` | `AirPlayPersistence.smali` | 不再把 `EXISTING_WIFI` 强制改回 `MANUAL` |
| `radio-name-fallback-controller` | `CarPlayController.smali` | hop 读不到蓝牙名时回退标准 API |
| `radio-name-fallback-resolver` | `WirelessIdentityResolver.smali` | 同上，供身份协商使用 |

## 使用

```bash
apktool d DiPlay.apk -o base

python apply_smali_patches.py base --dry-run   # 先校验锚点
python apply_smali_patches.py base

apktool b base -o DiPlay_unsigned.apk
apksigner sign --key platform.pk8 --cert platform.x509.pem \
    --out DiPlay_signed.apk DiPlay_unsigned.apk
```

脚本特性：

- **锚点 + 次数校验**：每个补丁声明期望出现次数，不匹配就整体失败
- **只读试运行**：`--dry-run` 不写文件
- **自动备份**：写入前生成 `*.orig`
- **幂等**：已打过的补丁会显示 `SKIP`

## 版本适配

`patches.json` 里的锚点来自 **DiPlay Legacy Geely V044 / 0.2.21**。
DiPlay 升级后 smali 的行号和寄存器可能变化，但方法名和调用序列通常稳定。
如果某个补丁报 `FAIL`，按下面顺序处理：

1. `apktool d` 新版本，搜索 `cond_4` / `cond_1` 附近的 `if-ne`，确认语义相同
2. 搜索 `CarBluetoothHops;->a`，确认仍在 `requireCarHopRadioName` 中
3. 更新 `patches.json` 的 `anchor` / `count`，先 `--dry-run` 验证
4. 提交 PR 时附上新版本号

## ⚠️ 寄存器类型警告

插入 smali 时**不要**复用已有寄存器做不同类型**。真实翻车案例：

```smali
invoke-virtual {v0}, Ljava/lang/String;->length()I
move-result v1          # v1: int
if-nez v1, :cond_x
return-object v0
```

而 `v1` 在原方法里是 `String` 引用。Dalvik verifier 在方法入口做类型合并：

```
java.lang.VerifyError: Rejecting class CarPlayController
```

整个类被拒绝加载，应用直接闪退。

规则：

1. 先读目标方法开头的 `.locals N` 和已有寄存器用途
2. 只使用**未被占用的高位寄存器**，或用 `move-object` 明确移动
3. 优先在方法尾部追加，避开 verifier 的合并点
4. 只做非空判断，不做需要新寄存器的运算

## 详细说明

- [热点模式强制降级](patches/hotspot-mode.md)
- [蓝牙名称回退](patches/radio-name-fallback.md)

## 配置写入

补丁只改代码逻辑，运行时配置仍在
`/data/data/com.shihab.diplay/shared_prefs/xcertplay_airplay.xml`。
模板见 [`config/example-prefs.xml`](../config/example-prefs.xml)。

改完 prefs 必须 `am force-stop`，否则内存缓存会覆盖文件。
