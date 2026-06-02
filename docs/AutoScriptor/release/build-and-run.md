# 发行构建与运行说明

本文说明**如何构建发行物**、**脚本参数与缓存**、**桌面端三种产物形态**，以及**最终用户侧的安装流程**（含 MuMu/ADB）。Nuitka 编译选项与 post 拷贝细节见同目录 [nuitka-reference.md](./nuitka-reference.md)。

---

## 0. 每次构建前的强制梳理

发行构建前必须先完成一次完整梳理，即使这次代码改动看起来很小。不要直接复用上一次构建判断。

1. **读取规则和 skill**：`docs/agents/project-rules.md`、本文件、[nuitka-reference.md](./nuitka-reference.md)、[vm-acceptance.md](./vm-acceptance.md)，并使用 Codex 的 `autoscriptor-install-deployment-release`、`autoscriptor-packaging-content-config`、`windows-powershell-command-hygiene` skills。
2. **确认版本与产物状态**：检查 `git status --short`、`webapp/package.json`、`AboutPanel.js`、`dist/`、`dist_electron/`、`release_snapshots/`。
   - `dist_electron/` 不会被 `build_release.py` 自动清空。构建前必须辨认并清理遗留的手工安装目录或旧解包目录（例如包含 `data/accounts/*.json`、日志或本机运行数据的目录），只保留明确要复用/对照的历史发行包与 `release_snapshots/`。
3. **归类变更面**：
   - Python 后端、任务、调度、runtime bootstrap：完整 Nuitka 构建；同一 `x.y` 线还要生成累计小版本更新包。
   - WebUI 静态文件或 Electron 壳：若 `dist/gui.dist` 已由同一代码基线验证通过，可 `--skip-nuitka`；但更新包仍要显式包含需要落到 backend 的静态文件。
   - 后端运行时外置资源：例如 WebUI static/vendor、collector 脚本、JSON 数据、docs 中被运行时读取的文件，必须确认 `gui.dist`、`backend.zip`、小版本更新包三处都能覆盖。
   - Nuitka 运行时、stdlib/importlib bootstrap、依赖、安装器或更新契约：完整包是必需；是否提升 `minor` 需按版本规则向用户确认。
4. **本地预检**：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING='utf-8'
git status --short
.\.venv-nuitka\Scripts\python.exe -X utf8 scripts\verify_packaging_prereqs.py
cd webapp
npm run test:installer
npm run test:release-update
cd ..
```

5. **敏感信息扫描**：PowerShell 不要写裸 `config*`，用明确路径，并排除第三方参考代码、vendored/minified 前端库和 `node_modules` 噪音。不要为了扫描把真实账号值打印出来；必要时先打码，再逐条分类。

```powershell
rg -n "password|account|token|secret|private_key|ssl_key|credential|BEGIN .*PRIVATE KEY" `
  "config.json" "config template.json" docs/AutoScriptor docs/agents services scripts webapp test `
  -g "!docs/refs/**" `
  -g "!docs/AutoScriptor/3rdparties/**" `
  -g "!services/webui/vendor/**" `
  -g "!webapp/node_modules/**"
rg -n "password|account|token|secret|private_key|ssl_key|credential|BEGIN .*PRIVATE KEY" `
  dist dist_electron -g "*" 2>$null
Get-ChildItem -Recurse -File -Filter "*.map" -ErrorAction SilentlyContinue dist,dist_electron
```

逐条分类。唯一允许的真实明文例外是 4399 资讯公共凭据 `85rwm3janyyc` / `123456`。

生成小版本更新包后必须复核 `update_manifest.json`。如果当前 diff 含 WebUI static、collector 脚本、运行时 JSON/docs 等外置 backend 资产，但 manifest 只有 `backend/autoscriptor-engine.exe`（脚本输出类似 `替换文件: 1`），该升级包不完整，必须用 `--include-backend` 逐项纳入这些文件后重建。

6. **失败处理纪律**：如果构建或 packaged runtime smoke 出现新失败，先把根因、复现命令、修复规则写入本文件、[nuitka-reference.md](./nuitka-reference.md) 或 `docs/agents/skill-references/`，并同步本地 Codex skill；然后再重试构建。中断的构建和 smoke 失败的构建都不是可发布产物。
   - `importlib`/stdlib bootstrap 修复不能只看源码 direct probe。普通 Python 里通过，不代表 compiled Nuitka 启动早期的 `dist/gui.dist/importlib` 解析顺序也通过；必须等待 `autoscriptor-engine.exe --runtime-import-smoke` 通过。
   - packaged smoke 若出现 `importlib.readers`、`multiprocessing.Manager` 或 Starlette `Protocols can only inherit from other protocols`，归类为 copied stdlib 启动期组合问题：先同步经验，再补 importlib resources 子模块、真实 `multiprocessing` package 载入或 `typing` allowlist 修复。
   - `multiprocessing.Manager` 的修复只应让 `gui.py` 启动期加载 copied stdlib package，并由 post-copy 保证 `multiprocessing/` 存在；不要把 `multiprocessing` 加进 `--nofollow-import-to`，否则 Nuitka 可能在最后阶段报 `multiprocessing: Conflict between user and plugin decision`。
   - 若产物里已有 `encodings/idna.py` 或 `multiprocessing/context.py`，但 smoke 仍报 `No module named 'encodings.idna'` 或 `cannot import name 'context' from 'multiprocessing'`，不要继续补拷文件；这是 compiled runtime 的 package 壳/`sys.modules` 状态未修复，应在 `gui.py` 启动期挂载 copied package 搜索路径并清理半初始化子模块。
   - 若 direct probe 可加载 copied `multiprocessing`，但 compiled smoke 仍报 `cannot import name 'context' from 'multiprocessing'`、`No module named 'multiprocessing.util'` 或启动期 stderr 报 `cannot import name 'process' from 'multiprocessing'`，不要把 source-mode 结果当通过。Nuitka 会把 `multiprocessing` 编成 namespace package 并带 `multiprocessing` plugin post-load；修复必须先预载并挂载 copied `multiprocessing.process` 与 `multiprocessing.util`，再加载 copied `context` 并在加载子模块时预置父包属性，稳定 `context/reduction` 循环导入后，从 `context._default_context` 导出 `Manager` / `Process` 等 API。
   - 若 `--runtime-import-smoke` 已通过，但后续 `engine --electron` 启动在 `Event()` 报 `No module named 'multiprocessing.synchronize'`，说明实际 WebUI worker 生命周期触发了 `context._default_context.Event()` 的懒加载。启动修复必须在 engine 创建 `Event` 前预载并挂载 copied `multiprocessing.synchronize`，单元测试也要实际调用 `Event()`，不要只检查父包上有同名属性。
   - 若 `Event()` 已通过但 `Process.start()` 报 `No module named 'multiprocessing.popen_spawn_win32'`，说明 Windows spawn 启动路径还未覆盖。启动修复应在导出 `context._default_context` API 到父包后，再预载 `multiprocessing.reduction`、`multiprocessing.spawn` 和 `multiprocessing.popen_spawn_win32`；`spawn.py` 会从父包导入 `get_start_method` / `set_start_method`，顺序反了会在 direct probe 中失败。测试要模拟 `Process.start()` 导入 `_Popen`，不要只构造 `Process` 对象。
   - 若 `--runtime-import-smoke` 通过、但 `engine --electron` 报 `program tried to call itself with '-c' argument`，说明 Windows multiprocessing spawn 已进入真实自执行路径，而 Nuitka 的 self-execution deployment guard 拦截了当前 exe。发行构建必须保留 `--no-deployment-flag=self-execution`；不要把它当成缺模块或端口占用问题。
   - 若保留 self-execution flag 后 `engine --electron` 不 ready、stdout/stderr 为空，同时进程列表出现大量 `autoscriptor-engine.exe` 且命令线为 `dist\gui.dist\python.exe -S -s -c "from multiprocessing.spawn import spawn_main..."`，这是 Windows spawn 走了非 frozen `-c` 路径并递归重进主程序。先用 `taskkill /IM autoscriptor-engine.exe /F /T` 清理本轮进程风暴；修复必须让 packaged runtime 在 single-instance 之前设置 `sys.frozen`、恢复真实当前 exe 到 `sys.executable`，并先执行 `multiprocessing.freeze_support()`，不要继续补模块或单纯延长 timeout。
   - 若 worker 已进入 `_webui_worker`，但 `uvicorn._subprocess` 调 `multiprocessing.allow_connection_pickling()` 时报 `cannot import name 'connection' from 'multiprocessing'`，说明 copied `multiprocessing/connection.py` 已存在但未被启动期父包挂载。应在导出 `context._default_context` API 后预载并 attach `multiprocessing.connection`，覆盖 Uvicorn supervisor/subprocess 导入路径。
   - VM 验收要分层报告。VirtualBox 干净机可能完成安装并让基础 WebUI 返回 200，但 `--runtime-import-smoke` 在 Paddle/OCR 导入处因 `paddle\base\libpaddle.pyd` 初始化失败或 `name 'libpaddle' is not defined` 失败。此时只能说安装器/基础 WebUI 通过，不能宣称 OCR、MuMu 或任务执行通过；需要在支持 AVX 的 VM 或真实 MuMu 机器上补跑 runtime/device acceptance。

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
| **`--electron-nsis`** | 生成 **系统 NSIS 安装程序**（`AutoScriptor_Zao_installer_<version>.exe`），**不是** HTML 向导那一屏。 |
| **`--electron-zip`** | 生成 **win-unpacked 的 zip 目录包**（调试用）；默认不启用。 |
| **`--electron-nsis-fast-install`** | 须与 **`--electron-nsis`** 同用：NSIS 使用 `compression=store`，**安装阶段更快**，安装包体积更大。 |

**环境变量（一般由脚本设置，也可手动）：**

| 变量 | 作用 |
|------|------|
| `AUTOSCRIPTOR_ELECTRON_NSIS=1` | 等价于 `--electron-nsis`（打 NSIS 时由 electron-builder 配置读取）。 |
| `AUTOSCRIPTOR_ELECTRON_ZIP=1` | 等价于 `--electron-zip`。 |
| `AUTOSCRIPTOR_NSIS_FAST_INSTALL=1` | NSIS 使用 store 压缩（安装更快）。 |
| `AUTOSCRIPTOR_CODE_SIGN=1` | 启用 Windows 代码签名。正式发布机需同时配置 electron-builder 支持的 `CSC_*` 证书环境变量或本机证书存储；无证书机器默认关闭签名，避免打包失败。 |
| `AUTOSCRIPTOR_STDLIB_SOURCE` | 可手动指定同版本 CPython `Lib` 源码目录；构建脚本只从中生成 `collections/_collections_abc` 源码 overlay，避免嵌入式 `python310.zip` 生成 namespace 空壳。 |
| `NUITKA_CACHE_DIR` | 脚本默认设为项目下 **`.nuitka-cache/`**（dll 等缓存）。 |

---

## 4. 构建结束时的耗时统计

脚本会在构建完成后打印 **`[build] 耗时统计`**，各段含义如下：

| 步骤名 | 含义 |
|--------|------|
| 清理 (clean) | 删除旧 `gui.dist` / `data` / `license` 等（保留 `gui.build` 除非 `--clean`）。 |
| Nuitka 编译 (subprocess) | 通过 `.nuitka-cache/run_nuitka_with_source_stdlib.py` 启动 Nuitka，使只含 `collections/_collections_abc` 的源码 overlay 优先参与定位。 |
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
| **NSIS** | 否（`--electron-nsis`） | `AutoScriptor_Zao_installer_<version>.exe` | 需要「开始菜单 / 控制面板卸载」等**系统级安装**时。 |
| **ZIP 目录包** | 否（`--electron-zip`） | `AutoScriptor_Zao_*.zip` | 解压整目录调试；**不是**默认分发形态。 |

### 6.1 系统 NSIS 安装器 vs HTML 安装向导（重要）

- **NSIS 安装程序**（`AutoScriptor_Zao_installer_<version>.exe`）：Nullsoft **默认向导**（选目录 → 进度条 → 完成），负责把 Electron 壳与随包文件释放到磁盘。
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

最终用户不应为了少量代码变更反复下载完整安装包。版本线按 `major.minor` 划分：

- **同一 `x.y` 线的小版本**：例如 `1.0.0 -> 1.0.1` 或 `1.1.0 -> 1.1.5`，使用累计小版本更新包 `AutoScriptor_Update_x.y.z.zip`。更新包必须包含从 `x.y.0` 到目标版本所需的全部 engine/少量附属文件变动，允许用户从同一 `x.y` 线任意更低小版本直接跳到目标版本。
- 小版本更新包不是底库，也不是完整安装包；它只适用于已经安装同一 `x.y` 线版本的目录。空机器或无旧安装树时必须先运行完整安装包。
- 若本次改动包含随 backend 读取的外置文件（例如 `services/webui/static/**`、`scripts/collect_zmxy_redeem_2026.py`、`docs/zmxy_redeem_codes.json`），同线更新包不能只替换 exe；这些文件必须通过 `--include-backend` 进入 `replace` 清单。
- **跨 `x.y` 线的大版本**：例如 `1.0.x -> 1.1.0`，使用完整安装包。依赖库、Nuitka 运行时、backend 目录布局、Electron 壳或安装器行为变化，都应走完整安装包。
- **本地小版本更新包**：WebUI“检查更新”页支持选择或拖入 `.zip`。Electron 主进程先 dry-run 校验 `update_manifest.json`、版本线、SHA-256、写入路径与用户数据保护；应用时停止 backend，备份旧文件，替换 `backend/autoscriptor-engine.exe` 等少量文件，失败则回滚并重启旧 backend。
- **`backend_incremental.zip`**：仍保留为特殊兜底，由 `scripts/release/release_backend_incremental.py` 对比旧 `backend.zip` 或旧 `gui.dist` 生成。它适合维护人员处理 backend 文件级差异，不作为普通用户默认更新路径。
- **发行版 manifest 内容更新**：WebUI 的“发行版更新”页调用 `/api/content-update/*`，按 `deploy.content_manifest_url` 拉取 HTTPS manifest、校验 hash/签名后写入允许的文件。该通道会拒绝覆盖 `config.json`、`data/config.json`、账号、`custom_task`、`battle_character`、日志和 `.autoscriptor` 状态目录。manifest 最小形状如下，签名字段由 `scripts/release/sign_content_manifest.py` 生成：

```json
{
  "content_version": "0.1.1",
  "min_shell_version": "1.0.0",
  "signature_ed25519": "BASE64_SIGNATURE",
  "artifacts": [
    {
      "kind": "raw",
      "relative_path": "services/webui/static/js/app.js",
      "url": "https://updates.example/app-0.1.1.js",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  ]
}
```

生成小版本更新包：

```powershell
python scripts/release/create_minor_update_package.py `
  --new-backend dist/gui.dist `
  --target-version 1.1.5 `
  --out dist/AutoScriptor_Update_1.1.5.zip
```

如果目标小版本还需要补少量目录或文件，可显式加入：

```powershell
python scripts/release/create_minor_update_package.py `
  --new-backend dist/gui.dist `
  --target-version 1.1.5 `
  --out dist/AutoScriptor_Update_1.1.5.zip `
  --include-backend services/webui/static/js/components/UpdatePanel.js `
  --mkdir data/assets/cache `
  --copy-if-missing docs/template.json=data/templates/template.json
```

WebUI 的“源码仓库更新”只服务开发/源码部署：它需要 `.git`，会执行 `git fetch/pull` 和 `pip install`。发行包里该通道会显示不可用，避免把最终用户带到必然失败的 Git 更新路径。

### 9.3 Dry run / lifecycle self-test

- 安装向导在“安装前确认”页提供 **“先做预检”**。该 dry run 只读取 `backend.zip`、目标目录状态、磁盘空间与随包 `data` 计划，不创建安装目录、不复制文件、不写注册表、不修改 MuMu/ADB 配置。
- 代码侧入口为 `dryRunPackagedInstall()`；增量更新也有 `dryRunApplyBackendIncremental()`，用于在真正复制 `.backend.incremental.*` 前校验 manifest、SHA-256 与基线是否匹配。
- 小版本本地更新入口为 `dryRunLocalReleaseUpdate()` / `applyLocalReleaseUpdate()`；测试覆盖同兼容线跳版本、跨线拒绝、降级拒绝、用户数据保护和失败回滚。
- 本地生命周期测试命令：

```powershell
cd webapp
npm run test:installer
npm run test:release-update
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

不要把整个 `dist_electron/` 当作可分发目录。该目录可能残留历史 `win-unpacked`、手工解包/安装目录、日志或用户 `data`。发布时只取本轮生成并通过扫描的具体文件（例如 `AutoScriptor_Zao_Install_x.y.z.exe`、`AutoScriptor_Zao_x.y.z.zip`）和需要验证的当前 `win-unpacked`。

---

## 11. 本地调试的两种用法（与发行包无关）

同一次完整构建后，开发者仍可：

1. **只测引擎**：`dist/gui.dist/` + `dist/data/`（或浏览器连本地服务）。
2. **测桌面端**：使用 `dist_electron` 中产物；portable 为单文件，NSIS 为系统安装器。

---

## 12. 安全与发布物

- 对外分发前确认**不包含**可还原业务逻辑的 **source map**（`*.map`）等；`npm run verify-pack` 会检查 `app.asar` 入口、`backend.zip` 内 `autoscriptor-engine.exe`、source map 泄漏、asar `package.json` 是否误带 `devDependencies`/npm scripts，以及是否把非白名单 npm 包打入公开产物。
- 发行流水线对 **`webapp`** 壳层会做**混淆/压缩 HTML**（见 `prepare-release-shell`），并排除 `*.map`；敏感逻辑仍勿放客户端明文。
- 打包前后都要扫描敏感信息。源码扫描排除 vendored/minified 第三方代码与三方参考文档，避免把第三方压缩包噪音当作本项目泄露；发布物扫描仍要覆盖 `dist` / `dist_electron` 并确认没有 source map、账号 JSON、私钥或非公开凭据。唯一允许的真实明文例外是 4399 资讯公共凭据 `news.account = "85rwm3janyyc"` / `news.password = "123456"`；这对凭据是项目资讯/论坛代理的公开运行依赖，必须保留明文，不得作为“泄露”清除。除此之外，账号、密码、token、deploy 密码、SSL/SSH 私钥、个人 `config.json` 和 `data/accounts/*.json` 都不得进入公开发布物。
- 第三方加密库源码里可能含 `BEGIN ... PRIVATE KEY` 的解析标记字符串；这不是项目秘密。第三方测试夹具若包含公开 PEM 示例（例如 `Crypto/SelfTest`），发行后处理应剪掉，避免发布扫描噪音和不必要体积。
- 正式对外版本建议启用代码签名：发布机配置证书后设置 `AUTOSCRIPTOR_CODE_SIGN=1`。没有证书时安装包仍可生成，但 Windows SmartScreen/杀软信任度会低于签名版本。

---

## 13. 常见问题

| 现象 | 处理方向 |
|------|----------|
| 端口已被占用 | 结束上次 Python/Electron 进程；释放 WebUI 默认端口。共享 agent 规则见 `docs/agents/project-rules.md`。 |
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

- `build_release.py` 会在 electron-builder 后自动运行 `npm run verify-pack`，校验 Electron `app.asar` 入口、source map 泄漏、npm payload 白名单和 backend payload。它会在 `backend.zip` 缺失、zip 内不含 `autoscriptor-engine.exe`、asar 带 dev npm 元数据或非白名单 npm 包时失败。
- The installer treats a failing `MuMuManager version` command as a warning when ADB is usable. This matches runtime behavior: MuMuManager is useful for official lifecycle commands, while ADB is the stable fallback for app/package/input checks.
- In the installer UI, this case is displayed as a yellow warning instead of a red blocking error. Users can finish installation, then use WebUI `启动诊断` to inspect MuMuManager, ADB, App, NemuIpc, OCR and UI Map layers separately.
- `verify_packaging_prereqs.py` and `npm run verify-pack` also check the VC++ runtime DLLs used by native wheels (`msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll`, `concrt140.dll`). `build_release.py` copies them into `backend.zip` when they are present in the Windows runtime directory.
