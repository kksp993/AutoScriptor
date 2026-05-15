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
2. **HTML 向导**：选择安装根目录 → 解压 `backend.zip` → 复制 `data` → 自动写入/探测 **MuMu**（`applyMumuConfig`）→ **环境验证页**确认 **MuMu 目录 / 模拟器 exe / adb** 路径。
3. 完成后启动主程序（`installer:launch` → 正常窗口 + 托盘）。

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

- 对外分发前确认**不包含**可还原业务逻辑的 **source map**（`*.map`）等。
- 发行流水线对 **`webapp`** 壳层会做**混淆/压缩 HTML**（见 `prepare-release-shell`），并排除 `*.map`；敏感逻辑仍勿放客户端明文。

---

## 13. 常见问题

| 现象 | 处理方向 |
|------|----------|
| 端口已被占用 | 结束上次 Python/Electron 进程；释放 WebUI 默认端口等见项目内 Cursor 规则 `webui.mdc`（若已配置）。 |
| 构建失败 | 查看完整终端输出；Nuitka 见 [nuitka-reference.md](./nuitka-reference.md)。 |
| 安装向导报找不到 `backend.zip` | 确认完整构建过 `dist/backend.zip` 并重新打 Electron；见本文第 7 节。 |
| 想要「和开发时一样的窗口应用」 | 使用含 Electron 的构建（不要 `--skip-electron`）；portable 首次运行即向导。 |

---

## 14. 文档关系

| 文档 | 用途 |
|------|------|
| **本文** | 构建参数、缓存、产物形态、NSIS/HTML 区别、安装流程与排错 |
| [nuitka-reference.md](./nuitka-reference.md) | Nuitka 选项、post 拷贝、嵌入式 Python、验收清单等 |

---

## 15. Current Packaging Checks

- `npm run verify-pack` validates both the Electron `app.asar` entry and the backend payload. It fails if `backend.zip` is missing from the unpacked app root/resources, or if that zip does not contain `autoscriptor-engine.exe`.
- The installer treats a failing `MuMuManager version` command as a warning when ADB is usable. This matches runtime behavior: MuMuManager is useful for official lifecycle commands, while ADB is the stable fallback for app/package/input checks.
- In the installer UI, this case is displayed as a yellow warning instead of a red blocking error. Users can finish installation, then use WebUI `启动诊断` to inspect MuMuManager, ADB, App, NemuIpc, OCR and UI Map layers separately.
