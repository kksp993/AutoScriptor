# 发行构建与运行说明

本文说明**如何构建发行物**、**脚本参数与缓存**、**桌面端三种产物形态**，以及**最终用户侧的安装流程**（含 MuMu/ADB）。Nuitka 编译选项与 post 拷贝细节见同目录 [nuitka-reference.md](./nuitka-reference.md)。

---

## 1. 桌面客户端是什么

「桌面客户端」指 **Electron 壳 + 本机后端服务**：窗口里加载同一套 Web 界面，与在仓库里 **`webapp` 目录执行 `npm start`** 的交互方式一致（**不是**单独开一个浏览器页当作产品主入口）。

- **开发调试**：在 **`webapp/`** 下执行 `npm install` 与 `npm start`（等价于 `electron .`）。
- **发行版用户**：使用构建产物中的 **单文件 exe** 或 **系统安装程序**；后端为 Nuitka 打包的引擎（无需本机 Python 源码树）。

---

## 2. 构建入口与推荐命令

由仓库根目录 **`scripts/build_release.py`** 完成完整流水线（Nuitka → `collect_data` → `backend.zip` → Electron）。

**推荐（默认 portable 单 exe + 并行编译）：**

```powershell
cd D:\Projects\AutoScriptor
.\.venv-nuitka\Scripts\python.exe scripts\build_release.py -j 16
```

- **`-j N`**：传给 Nuitka 的 `--jobs=N`（C 编译并行数），可按 CPU 核数调整。
- 勿与 **`--clean`** 同时使用于日常迭代（见下文「增量缓存」）。

**仅重打 Electron（引擎已存在）：**

```powershell
.\.venv-nuitka\Scripts\python.exe scripts\build_release.py --skip-nuitka -j 16
```

需已有可用的 `dist\gui.dist` 与 `dist\backend.zip`（或先完整构建一次）。

---

## 3. `build_release.py` 参数一览

以 **`python scripts/build_release.py --help`** 为准；以下为常用项备忘。

| 参数 | 作用 |
|------|------|
| **`-j` / `--jobs N`** | Nuitka C 编译并行任务数（内部 `--jobs=N`）。 |
| **`--clean`** | 额外删除 `dist/gui.build`，**冷编译**（最慢）；依赖或 Nuitka 大版本升级、怀疑缓存损坏时用。**日常不要加。** |
| **`--skip-nuitka`** | 跳过 Nuitka，沿用已有 `dist/gui.dist`（适合只改 webapp/Electron）。 |
| **`--skip-electron`** | 跳过 `backend.zip` 与 electron-builder（只产出引擎 + `dist/data`）。 |
| **`--clean-only`** | 只执行清理后退出。 |
| **`--electron-nsis`** | 生成 **系统 NSIS 安装程序**（`AutoScriptor_Zao_installer.exe`），**不是** HTML 向导那一屏。 |
| **`--electron-zip`** | 生成 **win-unpacked 的 zip 目录包**（调试用）；默认不启用。 |
| **`--electron-nsis-fast-install`** | 须与 **`--electron-nsis`** 同用：NSIS 使用 `compression=store`，**安装阶段更快**，安装包体积更大。 |

**环境变量（一般由脚本设置，也可手动）：**

| 变量 | 作用 |
|------|------|
| `AUTOSCRIPTOR_ELECTRON_NSIS=1` | 等价于 `--electron-nsis`（打 NSIS 时由 electron-builder 配置读取）。 |
| `AUTOSCRIPTOR_ELECTRON_ZIP=1` | 等价于 `--electron-zip`。 |
| `AUTOSCRIPTOR_NSIS_FAST_INSTALL=1` | NSIS 使用 store 压缩（安装更快）。 |
| `AUTOSCRIPTOR_CODE_SIGN=1` | 启用 Windows 代码签名。正式发布机需同时配置 electron-builder 支持的 `CSC_*` 证书环境变量或本机证书存储；无证书机器默认关闭签名，避免打包失败。 |
| `NUITKA_CACHE_DIR` | 脚本默认设为项目下 **`.nuitka-cache/`**（dll 等缓存）。 |

---

## 4. 构建结束时的耗时统计

脚本会在构建完成后打印 **`[build] 耗时统计`**，各段含义如下：

| 步骤名 | 含义 |
|--------|------|
| 清理 (clean) | 删除旧 `gui.dist` / `data` / `license` 等（保留 `gui.build` 除非 `--clean`）。 |
| Nuitka 编译 (subprocess) | `python -m nuitka` 子进程。 |
| Nuitka 后处理 (拷包/补文件) | `copy_nofollow_*`、distutils、wave、pypinyin 等。 |
| 收集数据 (collect_data) | 生成 `dist/data/`。 |
| 打包 backend.zip | 将 `gui.dist` 打成 zip。 |
| Electron 壳层准备 | `npm run prepare-release-shell`（混淆/压缩 HTML 等）。 |
| Electron 打包 | `electron-builder`（portable / NSIS / zip 视配置而定）。 |

**「各步骤合计」与「总耗时 (wall)」** 在保留两位小数时可能显示相同；中间若有极短未计时间隔，差值通常可忽略。

---

## 5. 增量缓存与加速（避免「改一行也一小时」）

| 路径/行为 | 说明 |
|-----------|------|
| **`dist/gui.build/`** | Nuitka 增量编译目录；**未使用 `--clean` 时会保留**，重编更快。 |
| **`.nuitka-cache/`** | 脚本设置 `NUITKA_CACHE_DIR` 指向此处。 |
| **勿滥用 `--clean`** | 会删掉 `gui.build`，等于冷编。 |
| **只改 Python、不要桌面包** | 加 **`--skip-electron`**。 |
| **只改 webapp、引擎已就绪** | 先保证有完整 `dist/gui.dist`，再加 **`--skip-nuitka`**。 |

---

## 6. 三种桌面产物形态（默认 / 可选）

由 **`webapp/electron-builder.staging.config.js`** 控制（`build_release.py` 通过环境变量切换）。

| 形态 | 默认？ | 产物（示例） | 适用场景 |
|------|--------|----------------|----------|
| **portable 单文件** | **是** | `造笔.exe` | 对外分发 **一个 exe**；首次运行即 **HTML 安装向导**（解压引擎 → MuMu/ADB）。 |
| **NSIS** | 否（`--electron-nsis`） | `AutoScriptor_Zao_installer.exe` | 需要「开始菜单 / 控制面板卸载」等**系统级安装**时。 |
| **ZIP 目录包** | 否（`--electron-zip`） | `AutoScriptor_Zao_*.zip` | 解压整目录调试；**不是**默认分发形态。 |

### 6.1 系统 NSIS 安装器 vs HTML 安装向导（重要）

- **NSIS 安装程序**（`AutoScriptor_Zao_installer.exe`）：Nullsoft **默认向导**（选目录 → 进度条 → 完成），负责把 Electron 壳与随包文件释放到磁盘。
- **HTML 安装向导**（`webapp/renderer/installer.html`）：**Electron 窗口**，与开发时同一套界面逻辑；负责 **解压 `backend.zip` 到用户所选目录**、**复制 data**、**MuMu/ADB 路径校验**（`install-packaged.cjs` + `mumu-detect.cjs`）。

**默认 portable 流程**：用户**不经过 NSIS**；运行 `造笔.exe` 后，首次启动即进入 **HTML 向导**。大体积引擎解压发生在向导内，**不是** NSIS 那一屏。

### 6.2 NSIS 安装阶段很慢或卡在进度条

常见原因：**解压 + 写盘 + Windows Defender 扫描**。处理方向：

- 等待更久（大包 + 杀软可能十几分钟）。
- 将安装目录或构建输出目录加入杀毒**排除项**（临时）。
- 打包 NSIS 时使用 **`--electron-nsis-fast-install`**（或 `AUTOSCRIPTOR_NSIS_FAST_INSTALL=1`），`compression=store`，安装阶段解压更快，安装包更大。

---

## 7. `backend.zip` 在包内的位置与运行时解析

安装向导从 **`resources/backend.zip`** 或 **与 `造笔.exe` 同目录的 `backend.zip`** 读取（见 `electron-builder` 的 **`extraFiles`** 与 `main.js` 中 `getBackendZipPath()`）。

- **原因**：portable（NSIS 自解压）在部分环境下 **`process.resourcesPath` 与资源实际落点不一致**，仅放 `extraResources` 可能导致找不到 zip。
- **现状**：构建将 **`dist/backend.zip`** 以 **`extraFiles` → `backend.zip`** 打到 **应用程序根目录**（与 exe 同级），运行时优先检测该路径。

若用户看到「找不到 backend.zip」：**确认使用完整 `build_release.py` 生成 `dist/backend.zip` 后重新打 Electron 包**。

---

## 8. 安装向导 UI（「正在安装」页）

- 发行版 **`install-packaged.cjs`** 只发送 **`progress` / `log` / `complete`**，**不发送** `step` 事件。
- 历史上曾有四格「步骤列表」，与 Python 开发安装脚本的 `step` 事件绑定；**发行版无法点亮**，已与真实流程不一致。
- **当前设计**：已移除该四格列表；**以进度条与日志为准**，避免误导。

开发模式若仍用 Python `install_steps.py`，可能收到 `step` 事件，仅用于更新副标题，不再有四格 UI。

---

## 9. 发行版安装流程（最终用户）

1. 运行 **`AutoScriptor_Zao_Install.exe`**（portable 会自解压到临时目录再启动，**用户数据**仍通过 `install.json` 指向正式安装根目录）。
2. **HTML 向导**：选择安装根目录 → 预检磁盘空间与 `backend.zip` 完整性 → 解压到 `.backend.new.*` 临时目录 → 校验 `autoscriptor-engine.exe` → 事务切换 `backend` → 合并 `data`（保留用户账号/脚本/角色数据）→ 自动写入/探测 **MuMu**（`applyMumuConfig`）→ **环境验证页**确认 **MuMu 目录 / 模拟器 exe / adb** 路径。
3. 完成后启动主程序（`installer:launch` → 正常窗口 + 托盘）。

### 9.1 修复安装 / 更新 / 卸载策略

- **修复安装**：允许选择已有造笔安装目录，不要求空目录；旧 `backend` 会先备份为 `.bak.*`，新引擎校验成功后再切换，失败时回滚旧引擎。
- **增量更新**：`backend_incremental.zip` 会先复制当前 `backend` 到 `.backend.incremental.*`，按清单校验旧文件 SHA-256，再替换并校验新文件 SHA-256；基线不匹配时会中止，不破坏旧引擎。
- **用户数据**：默认保留 `data/config.json`、`data/accounts/*.json`、`data/custom_task/`、`data/battle_character/`，随包基础数据只做合并更新。
- **进程占用**：安装前只结束安装目录内的后端进程，并且只清理属于造笔安装目录的 5000 端口监听，避免误杀其他本地服务。
- **卸载**：安装目录写入 `卸载造笔.bat` 与 `彻底卸载造笔.bat`。控制面板/默认卸载保留 `data`；彻底卸载才移除整个安装目录。

### 9.2 发行版更新通道

最终用户不应为了少量代码变更反复下载完整安装包。当前发布链路区分三种更新：

- **完整安装包**：首次安装、壳层/安装器大改、增量基线不匹配时使用，体积最大但最稳。
- **`backend_incremental.zip`**：由 `scripts/release/release_backend_incremental.py` 对比旧 `backend.zip` 或旧 `gui.dist` 生成，仅包含变化文件和 `incremental_manifest.json`。安装器/Electron 会先 dry-run 校验基线 SHA-256，再事务切换 `backend/`。
- **发行版 manifest 内容更新**：WebUI 的“发行版更新”页调用 `/api/content-update/*`，按 `deploy.content_manifest_url` 拉取 HTTPS manifest、校验 hash/签名后写入允许的文件。该通道会拒绝覆盖 `config.json`、`data/config.json`、账号、`custom_task`、`battle_character`、日志和 `.autoscriptor` 状态目录。

WebUI 的“源码仓库更新”只服务开发/源码部署：它需要 `.git`，会执行 `git fetch/pull` 和 `pip install`。发行包里该通道会显示不可用，避免把最终用户带到必然失败的 Git 更新路径。

### 9.3 Dry run / lifecycle self-test

- 安装向导在“安装前确认”页提供 **“先做预检”**。该 dry run 只读取 `backend.zip`、目标目录状态、磁盘空间与随包 `data` 计划，不创建安装目录、不复制文件、不写注册表、不修改 MuMu/ADB 配置。
- 代码侧入口为 `dryRunPackagedInstall()`；增量更新也有 `dryRunApplyBackendIncremental()`，用于在真正复制 `.backend.incremental.*` 前校验 manifest、SHA-256 与基线是否匹配。
- 本地生命周期测试命令：

```powershell
cd webapp
npm run test:installer
```

测试会在 `%TEMP%` 下创建临时 release/安装目录，覆盖 dry run、非法非空目录、缺少引擎包、完整安装、修复安装、用户数据保留、卸载脚本 PowerShell 语法解析、增量更新、增量基线不匹配回滚。默认测试结束后删除临时目录；调试时可保留：

```powershell
$env:KEEP_INSTALLER_TESTS='1'
npm run test:installer
```

---

## 10. 输出目录分工

| 根目录 | 谁写入 | `clean()` 是否删除 |
|--------|--------|---------------------|
| **`dist/`** | Nuitka：`gui.dist/`；脚本：`data/`、`license/`；增量：`gui.build/` | 会删 `gui.dist`、`data`、`license`；可选 `--clean` 再删 `gui.build` |
| **`dist_electron/`** | 仅 electron-builder | **不会**删除（与 `dist/` 分离） |

electron-builder **不会清空你的 `dist/`**；每次打桌面包会刷新 **`dist_electron/`** 内内容。

---

## 11. 本地调试的两种用法（与发行包无关）

同一次完整构建后，开发者仍可：

1. **只测引擎**：`dist/gui.dist/` + `dist/data/`（或浏览器连本地服务）。
2. **测桌面端**：使用 `dist_electron` 中产物；portable 为单文件，NSIS 为系统安装器。

---

## 12. 安全与发布物

- 对外分发前确认**不包含**可还原业务逻辑的 **source map**（`*.map`）等；`npm run verify-pack` 会检查 `app.asar` 入口、`backend.zip` 内 `autoscriptor-engine.exe` 以及 source map 泄漏。
- 发行流水线对 **`webapp`** 壳层会做**混淆/压缩 HTML**（见 `prepare-release-shell`），并排除 `*.map`；敏感逻辑仍勿放客户端明文。
- 正式对外版本建议启用代码签名：发布机配置证书后设置 `AUTOSCRIPTOR_CODE_SIGN=1`。没有证书时安装包仍可生成，但 Windows SmartScreen/杀软信任度会低于签名版本。

---

## 13. 常见问题

| 现象 | 处理方向 |
|------|----------|
| 端口已被占用 | 结束上次 Python/Electron 进程；释放 WebUI 默认端口等见项目内 Cursor 规则 `webui.mdc`（若已配置）。 |
| 构建失败 | 查看完整终端输出；Nuitka 见 [nuitka-reference.md](./nuitka-reference.md)。 |
| 安装向导报找不到 `backend.zip` | 确认完整构建过 `dist/backend.zip` 并重新打 Electron；见本文第 7 节。 |
| 修复安装失败或提示基线不匹配 | 优先重试完整安装包；若是增量包，确认它与当前已安装版本匹配。失败前旧 `backend` 会保留或回滚。 |
| 卸载后仍看到 `data` | 默认卸载会保留用户数据。需要清空账号、脚本和角色数据时运行安装目录下的 `彻底卸载造笔.bat`。 |
| Windows 提示未知发布者 | 未启用代码签名或证书信任尚未建立。正式分发请在发布机配置证书并设置 `AUTOSCRIPTOR_CODE_SIGN=1` 重新构建。 |
| 想要「和开发时一样的窗口应用」 | 使用含 Electron 的构建（不要 `--skip-electron`）；portable 首次运行即向导。 |

---

## 14. 文档关系

| 文档 | 用途 |
|------|------|
| **本文** | 构建参数、缓存、产物形态、NSIS/HTML 区别、安装流程与排错 |
| [nuitka-reference.md](./nuitka-reference.md) | Nuitka 选项、post 拷贝、嵌入式 Python、验收清单等 |

---

## 15. Current Packaging Checks

- `build_release.py` 会在 electron-builder 后自动运行 `npm run verify-pack`，校验 Electron `app.asar` 入口、source map 泄漏和 backend payload。它会在 `backend.zip` 缺失或 zip 内不含 `autoscriptor-engine.exe` 时失败。
- The installer treats a failing `MuMuManager version` command as a warning when ADB is usable. This matches runtime behavior: MuMuManager is useful for official lifecycle commands, while ADB is the stable fallback for app/package/input checks.
- In the installer UI, this case is displayed as a yellow warning instead of a red blocking error. Users can finish installation, then use WebUI `启动诊断` to inspect MuMuManager, ADB, App, NemuIpc, OCR and UI Map layers separately.
