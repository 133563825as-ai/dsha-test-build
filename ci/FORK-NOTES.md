# FORK-NOTES — 这是 fork 行为，不是官方仓库状态

临时仓库 `133563825as-ai/dsha-test-build` 只用于产出一个**可安装的 debug APK**，
用来验证四个本地修复。它不向 `DSH-APP/DSHA` 推任何东西，也不开 PR。

## 1. 源码怎么进来
`ci/patches/dsha-four-fixes.patch` = `git diff <upstream 70e37a7> <本地集成分支 test/all-fixes>`。
workflow 里 `actions/checkout` 拉 **DSH-APP/DSHA@70e37a7**（只读），然后
`git apply` 这个补丁。补丁本地已用 `git apply --check` 验证干净应用。

集成分支 `test/all-fixes`（本地，未推上游）由三个 merge 构成，无冲突：

| 来源分支 | 提交 | 修复 |
| --- | --- | --- |
| `fix/pip-transition-relayout` | 16efaca | 画中画过渡期重布局闪烁 |
| `fix/vscreen-generation-and-frame-gate` | 85a2cb8 + fb93a11 | 虚拟屏 generation 同步 + 帧栅栏时间窗 |
| `feat/dsha-pickfile-bridge` | 87a4eb9 + 2e1bab6 | 网页附件选择桥 window.DSHA.pickFile |
| `fix/adb-wheel-parent-link` | 3f4b24c | ADB wheel 站点目录 / PARENT_LINK |

## 2. 与官方 `ci-package.yml` 的偏离（如实记录）

### 2.1 资产解包：用 `ci/unpack-inputs.py`，**没有**改上游 `tools/ci-assets.py`
官方 `python3 tools/ci-assets.py --url ... --sha256 ...` 在本场景下必然失败：

* `verify_sources()` 把 `NAMES` 里每个名字都对 `app/src/main/assets/runtime-descriptor.json`
  取摘要。bundle 里的 `python-support.bin`、`adb-wheels.tar.gz` **未在 descriptor 登记**，
  直接 `CI_ASSET_SOURCE_MISMATCH`。
* descriptor 登记的 `offline-rootfs.bin` 是**源文件** `0a680b56…`（约 304 MB，只在
  官方构建机上），而 bundle / APK 里的是**优化产物** `b9fe8a04…`（85,783,057 B）。

本 fork **没有**触碰上游脚本，而是把放宽逻辑单独放在临时仓库的 `ci/unpack-inputs.py`
（便于交接单里如实说明）。它保留了官方 `allowed()` / `bounded()` 的全部约束：
成员白名单（`app/src/main/assets/<NAMES>` + `tools/recovery-runtime/archives/<lock 里的 asset>`，
本 bundle 共 11 个）、整包 SHA-256 门、成员数 / 成员名集合 / 总量 2 GiB 门、
逐成员流式写出、不采用归档内路径、不写目录项、禁止符号链接父目录。
额外增加：断言全部成员为 `ZIP_STORED`。

### 2.2 跳过的 Gradle 门禁
```
-x :app:verifyRuntimeDescriptorInputs
-x :app:prepareRuntimeDescriptor
```
原因同 2.1 的第二个 bullet：`verifyRuntimeDescriptorInputs` 要求
`DESCRIPTOR_SOURCE_BYTES: offline-rootfs.bin` 等于 304 MB 源文件摘要。
* `prepareRuntimeDescriptor` 会**原地重写** `app/src/main/assets/runtime-descriptor.json`，
  跳过它意味着 APK 里带的是仓库里 checkout 出来的那份 descriptor。
* 这两条**不参与 APK 的字节内容**（`prepare-*-assets.py` 全都不读 descriptor），
  跳过只影响 descriptor 自校验，不影响打包用的资产。

### 2.4 依赖校验锁只覆盖 Windows（新增一处补齐）
`gradle/verification-metadata.xml` 是在 Windows 机器上生成的（全文 `-linux` 出现 **0** 次），
只钉了 `aapt2-9.1.1-14792394-windows.jar`。Linux 上 AGP 通过内部 detached configuration
解析 `aapt2-9.1.1-14792394-linux.jar`，strict 依赖校验直接失败：

```
> Dependency verification failed for configuration ':app:detachedConfiguration2'
  One artifact failed verification: aapt2-9.1.1-14792394-linux.jar (com.android.tools.build:aapt2:9.1.1-14792394) from repository Google
```

处理方式：**没有**用 `--dependency-verification=off|lenient` 整体放水，也**没有**用
`--write-verification-metadata` 无脑接受解析结果，而是由 `ci/patch-verification-metadata.py`
只补这一条，摘要另行从 Google Maven 离线取回并核对：

```
https://dl.google.com/dl/android/maven2/com/android/tools/build/aapt2/9.1.1-14792394/aapt2-9.1.1-14792394-linux.jar
sha256 e7ae17af6e4093c771243e82d66462353de87befaac206bfb43e557ac1c34440   (2,331,128 B)
```

其余仍为 strict：已钉的条目一个没动，任何**其他**未登记产物依旧会让构建失败。
（副作用提示：上游自己的 `.github/workflows/ci-package.yml` 也是 `runs-on: ubuntu-24.04`，
按同样逻辑应该会撞到这里 —— 说明该 workflow 可能从未在 Linux 上真正跑通过。）

### 2.3 其他
* 不装 NDK（本仓库无 native 编译，`jniLibs` 是预编译的）。
* runner 镜像（`ubuntu-24.04`，镜像版本 `20260927.320`）**完全没有预装 Android SDK**，
  `sdkmanager: command not found`（exit 127）。workflow 里显式下载
  `commandlinetools-linux-16111833_latest.zip`（sha256
  `0877a1d048fe4a24efe2eff536ca4223f7adeb58648bb81909d33c446918cfa8`）解到
  `$HOME/android-sdk/cmdline-tools/latest`，再装 `platforms;android-37.0` +
  `build-tools;36.0.0`。**不假设 runner 自带 SDK。**
* 不用发布密钥；debug 用 Android 标准 debug keystore 自动签名 → 可直接安装。
* `applicationId` 是 `com.dsh.client`，与已装机的 `com.dsh.clienu` 不同包名，可并存。
* 新增一个 `fix-unit-tests` job（`continue-on-error`），额外跑
  `PictureInPicturePolicyTest` / `VirtualScreenPolicyTest` /
  `VirtualScreenGenerationSyncTest`，作为四个修复的行为证据；它不阻塞 APK 产物。
* 拆分 `assembleStandardDebug` / `assembleLowDebug` 为两个独立 job（而非一条
  `assembleDebug`），这样任一 flavor 卡住/超时都不会吞掉另一个的产物。
