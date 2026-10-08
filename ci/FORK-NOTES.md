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

## 2. 产物形态（用户决定）

* **只出 standard**：目标机 vivo V2463A / Android 16 (SDK 36)，`minSdk 30` 已覆盖；
  `low`（minSdk 23 / Gecko）不构建 —— 两个 flavor `applicationId` 相同、签名不同，
  同机只能装一个，多出一份只会造成混淆。
  （历史说明：run 37771605280 曾同时产出 standard + low 两份，
  `app-standard-debug.apk` 290,849,194 B / `app-low-debug.apk` 371,606,024 B，
  签名者证书不同，因为 standard / low 跑在不同 runner、各自现生成 debug.keystore。）
* **debug keystore 固定**：`ci/debug.keystore`（JKS，alias `androiddebugkey`，
  store/key pass `android`，`CN=Android Debug`，有效期至 2054），构建前
  `install -m 600` 到 `$HOME/.android/debug.keystore`，AGP 的默认 debug 签名配置就会用它。
  * 文件 sha256：`f5159a89f0bece07ffccbede9a3939a5afe4d6c0d7e3196adf73dd84c48b4ec0`
  * **证书 SHA-256：`fc9f42df825a203f7d2b1e8913bda0353a47b386fcba4fb5718860e01ac39eae`**
  * 构建 job 里有一道硬断言：APK 的 `apksigner verify --print-certs` 结果必须等于这个值，
    否则 job 失败。这样"后续包可覆盖安装"是**被验证的**，不是照抄的说法。
  * 已用 JDK 17 实测该 JKS 能被 `KeyStore.getInstance("JKS")`、`"PKCS12"` 和默认类型
    （pkcs12）三种方式加载，不依赖 AGP 用哪种 store type。
  * 为什么必须固定：用户装机后首启要解压内置 Ubuntu（数分钟）。如果每次 runner 现生成
    keystore，签名就变，下一个包只能卸载重装 + 再等一次解压。
* **发 GitHub Release**：standard APK 作为 release asset 上传，直链
  `https://github.com/<owner>/<repo>/releases/download/<tag>/<file>.apk`，
  手机浏览器可直接下（URL 无 token）。
* **trigger 只有 `workflow_dispatch`**（去掉 push）：因为 tag / patch 必须显式指定，
  避免一次无关 push 把已有 tag 的 release 覆盖掉。

## 3. 与官方 `ci-package.yml` 的偏离（如实记录）

### 3.1 资产解包：用 `ci/unpack-inputs.py`，**没有**改上游 `tools/ci-assets.py`
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

### 3.2 跳过的 Gradle 门禁
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

### 3.3 依赖校验锁只覆盖 Windows（新增一处补齐）
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

### 3.4 其他
* 不装 NDK（本仓库无 native 编译，`jniLibs` 是预编译的）。
* runner 镜像（`ubuntu-24.04`，镜像版本 `20260927.320`）**完全没有预装 Android SDK**，
  `sdkmanager: command not found`（exit 127）。workflow 里显式下载
  `commandlinetools-linux-16111833_latest.zip`（sha256
  `0877a1d048fe4a24efe2eff536ca4223f7adeb58648bb81909d33c446918cfa8`）解到
  `$HOME/android-sdk/cmdline-tools/latest`，再装 `platforms;android-37.0` +
  `build-tools;36.0.0`。**不假设 runner 自带 SDK。**
* 不用发布密钥（`signingConfigs.publish` 不参与）；debug buildType 走固定的
  `$HOME/.android/debug.keystore`（见第 2 节）→ 可直接安装、且跨次构建签名一致。
* `applicationId` 是 `com.dsh.client`，与已装机的 `com.dsh.clienu` 不同包名，可并存。
* `fix-unit-tests` job 额外跑
  `PictureInPicturePolicyTest` / `VirtualScreenPolicyTest` /
  `VirtualScreenGenerationSyncTest`，作为修复的行为证据；它是独立 job，
  失败不会影响 APK job（但会让整个 run 变红，属于有意的证据强度）。
* 构建命令用 `:app:assembleStandardDebug` 而不是 `:app:assembleDebug`，因为
  不再需要 low flavor（见第 2 节）。
* 历史记录：`test-1` 之前的第一次成功构建（run 37771605280）用的是 runner
  现生成的 debug keystore，`app-standard-debug.apk` 290,849,194 B /
  sha256 `d36bef652b6dca0f06e7f59f10ca18e22c62f5a63a329ba1f2e7fa16326b43f4` /
  cert `7da45404f66f5abdb4bf596f4f0e4d71753ca011a0058044606d1a19c8841ce1`。
  那一份**不能**被固定 keystore 之后的包覆盖安装，只适合一次性冒烟验证。
