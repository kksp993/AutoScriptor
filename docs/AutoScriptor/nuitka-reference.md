# Nuitka 资料与排错备忘（AutoScriptor 发行构建）

本文汇总官方文档与社区中**与 Windows / standalone / 排错**相关的入口，并记录本仓库在集成 Nuitka 时的实践结论。链接均为完整 URL，便于直接打开。

**整条发行流水线**（`build_release.py`、`backend.zip`、Electron portable/NSIS、增量缓存、安装向导）见 [release-build-and-run.md](./release-build-and-run.md)；**本文**侧重 Nuitka 选项与 post 拷贝，避免与上文重复。

---

## 一、官方文档（必读）

| # | 资源 | 摘要 |
|---|------|------|
| 1 | [Nuitka User Manual](https://nuitka.net/user-documentation/user-manual.html) | 版本要求、C 编译器（Windows：MSVC / MinGW64 / clang-cl 等）、`--mode=standalone` / `onefile` 等核心选项说明。 |
| 2 | [Tutorial: Setup and Build](https://nuitka.net/user-documentation/tutorial-setup-and-build.html) | 从零安装编译器、首包命令、建议先用 standalone 再试 onefile 等流程。 |
| 3 | [Use Cases](https://nuitka.net/user-documentation/use-cases.html) | 典型使用场景与分发方式说明。 |
| 4 | [Tips](https://nuitka.net/user-documentation/tips.html) | 性能与体积、调试技巧等补充建议。 |
| 5 | [Common Issue Solutions](https://nuitka.net/user-documentation/common-issue-solutions.html) | 常见问题的官方归纳与解决方向。 |
| 6 | [Nuitka Downloads / 获取方式](https://nuitka.net/doc/download.html) | 安装 Nuitka、商业版说明入口。 |
| 7 | [API documentation](https://nuitka.net/doc/api-doc.html) | 命令行选项与内部 API 索引（含 `--include-package-data` 等）。 |
| 8 | [Nuitka Package Configuration (YAML)](https://nuitka.net/doc/nuitka-package-config.html) | 复杂包（隐式依赖、数据文件、DLL）的 YAML 配置，用于替代大量手写 `--include-data-dir`。 |
| 9 | [Article: Standalone Mode](https://nuitka.net/posts/article-over-nuitka-standalone.html) | standalone 模式的设计思想与分发要点。 |
| 10 | [User Manual（镜像站点）](https://nuitka.github.io/Nuitka-website/doc/user-manual.html) | 与 `nuitka.net` 内容同源，便于镜像访问。 |

---

## 二、官方「信息页」（按报错查）

| # | 资源 | 摘要 |
|---|------|------|
| 11 | [Build failure in C / Scons backend](https://nuitka.net/info/scons-backend-failure.html) | C 后端失败时：优先检查**是否使用受支持的 C 编译器**；其次磁盘空间、内存、路径中的特殊字符等。 |
| 12 | [Python.h not found](https://nuitka.net/info/python-h-not-found.html) | `Python.h` 是编译所必需；Linux 各发行版安装 `python3-dev` 等命令表；Anaconda 说明头文件随 `python` 包。 |
| 13 | [Unwanted modules](https://nuitka.net/info/unwanted-module.html) | 用 `--nofollow-import-to`、`--noinclude-*` 等控制不需要的依赖；避免把测试/工具链拖进产物。 |

---

## 三、GitHub 议题（典型坑）

| # | 资源 | 摘要 |
|---|------|------|
| 14 | [Issue #2944 – CPython: problem with detecting imports](https://github.com/Nuitka/Nuitka/issues/2944) | 与「导入检测」阶段输出 `PROBLEM with ...`、verbose 追踪相关的讨论，便于理解 Nuitka 的静态分析边界。 |
| 15 | [Issue #3087 – pip module can't exe after build](https://github.com/Nuitka/Nuitka/issues/3087) | 在 standalone 中**不要指望运行时再去装 pip/动态拉子模块**；依赖应随构建一起打包好。 |
| 16 | [Issue #2385 – nofollow 与 stdlib](https://github.com/Nuitka/Nuitka/issues/2385) | `--nofollow-import-to` 对某些标准库场景的行为仍在演进，第三方包通常更可控。 |
| 17 | [Issue #2611 – Python from source checkout / Python.h 路径](https://github.com/Nuitka/Nuitka/issues/2611) | 非标准安装路径下 `Python.h` 可能不在 Nuitka 默认候选路径，需要手动对齐或贡献配置。 |
| 18 | [Issue #945 / winlibs gcc 检测](https://github.com/Nuitka/Nuitka/issues/945) | Windows 上 GCC 版本检测与 winlibs 的兼容问题（历史 issue，升级 Nuitka 后多数已修复）。 |

---

## 四、与本项目相关的结论（简）

1. **嵌入式 Python（embeddable zip）**  
   官方 Windows embeddable 包默认**不带**完整 `include` + `libs` 布局时，Nuitka 在 Scons 阶段会按 `getSystemPrefixPath()` 查找 `include/Python.h` 与 `libs/python310.lib`。若缺少，Windows 上会提示与「embeddable / 不完整开发文件」类似信息（见 `nuitka/build/SconsPythonBuild.py` 中候选路径逻辑）。  
   **可行做法**：在用于编译的 Python 前缀下补齐 `include/` 与 `libs/`（例如从 [python.org](https://www.python.org/downloads/) 完整安装或 NuGet `python` 包解压出 `tools/include`、`tools/libs`），或在本仓库 venv 的 `Scripts\include` / `Scripts\libs` 放置同名文件（与 `sys.base_prefix` 一致）。

2. **venv 的 `base_prefix` 指向 `Scripts`**  
   嵌入式 Python 创建的 venv 可能将 `sys.base_prefix` 设为 `.venv\Scripts`。Nuitka 会在此目录下找 `include` / `libs`，**与 `sysconfig.get_path('include')` 一致**，需保证该目录下确有 `Python.h` 与 `python310.lib`。

3. **导入检测与 pip**  
   若 `sys.path` 中含可导入的 `pip` 且触发了 `__pip-runner__` 等仅能在 `__main__` 下运行的模块，Nuitka 的导入检测可能报错。排错方向：升级 Nuitka、缩小 `sys.path` 污染、或临时排除有问题的 pip 内模块（仅用于构建环境，事后恢复）。

4. **大型科学计算 / 深度学习栈**  
   对 `paddle`、`scipy`、整棵 `matplotlib` 等做**全量编译**会极耗内存与时间。实践上通常对这类包使用 `--nofollow-import-to=...`，让运行时仍用 `.pyd`/DLL 与元数据打包（并配合 `--include-distribution-metadata` 等按需使用），具体以 `scripts/build_release.py` 为准。

5. **命令行选项**  
   不同 Nuitka 版本会废弃部分选项（例如旧版文档中的 `--no-pdb` 在 4.x 已不存在），应以 `python -m nuitka --help` 为准。

---

## 五、GitHub 补充（encodings / 路径）

| # | 资源 | 摘要 |
|---|------|------|
| 19 | [Issue #1102 – ModuleNotFoundError: encodings](https://github.com/Nuitka/Nuitka/issues/1102) | 讨论 standalone 运行时报 `encodings` 缺失、与 Python 安装形态/PATH 的关系；**不要用不完整的 Python 布局去承担「编译用解释器」角色**。 |
| 20 | [Issue #1426 – nofollow 与 standalone 报错体验](https://github.com/Nuitka/Nuitka/issues/1426) | `--nofollow-import-to` 在 standalone 下若仍被间接需要，报错信息可改进；打包策略要自行保证运行时依赖齐全。 |

---

## 六、本项目实测结论（重要）

1. **用「Windows embeddable 包 + venv」作为执行 `python -m nuitka` 的解释器时**，可能出现：`dist\*.dist` 内文件数量异常少、`autoscriptor-engine.exe` 启动阶段 `ModuleNotFoundError: No module named 'encodings'`（与 [Issue #1102](https://github.com/Nuitka/Nuitka/issues/1102) 同类现象）。仅向 `gui.dist` 手工复制 `python310.zip` 或完整 `Lib` 未必能修复，因运行时 `sys.path` 仍可能不包含这些目录。
2. **推荐做法**：使用 [python.org 官方 Windows x86-64 安装包](https://www.python.org/downloads/windows/) 安装 **完整版** Python 3.10（勾选 pip、可选「为所有用户安装」），再在其上新建 venv、安装依赖后执行 `scripts/build_release.py`。不要用 embeddable-only 布局作为唯一编译环境。
3. **`--include-distribution-metadata=opencv-python` 与 `--nofollow-import-to=cv2` 冲突**：Nuitka 会报「包含某发行版元数据但未包含关联包」。若对 OpenCV 使用 `nofollow`，应去掉对应 `opencv-python` 的 metadata 选项（本仓库 `build_release.py` 已按此处理）。

---

## 七、维护说明

- 升级 Nuitka 大版本后，请复查 [User Manual](https://nuitka.net/user-documentation/user-manual.html) 与 `python -m nuitka --help`。
- 若向 Nuitka 上游报 bug，请按 [scons-backend-failure](https://nuitka.net/info/scons-backend-failure.html) 建议：准备**最小复现**、注明 Python/Nuitka/编译器版本与完整日志。

---

## 八、本仓库构建流程一览（脚本 `scripts/build_release.py`）

日常运行方式（Electron、`npm start`）与构建命令的**对外备忘**见 [release-build-and-run.md](./release-build-and-run.md)；本节偏 Nuitka 与 post 拷贝细节。

**目录约定**：**`dist/`**（`gui.dist`、`data`、`gui.build` 等）与 **`dist_electron/`**（electron-builder 独占）为两个根；`build_release.py` 的 `clean()` 只清理前者子目录，**不删除** `dist_electron/`，避免与桌面包互相覆盖。electron-builder 仅从 `dist/` **复制**进安装包，不破坏 `dist/gui.dist`。

### 8.1 推荐解释器与命令

- 使用 **完整 Python** 创建的 **`.venv-nuitka`** 执行构建（避免 embeddable-only 导致 standalone 缺 `encodings` 等问题），见第六节。
- 典型命令：
  - 日常增量：`.venv-nuitka\Scripts\python.exe scripts\build_release.py --skip-electron`
  - 冷编 / 怀疑缓存损坏：同上并加 **`--clean`**（会删除 `dist/gui.build`）。

### 8.2 增量与缓存

| 机制 | 说明 |
|------|------|
| **保留 `dist/gui.build`** | 默认 `clean()` 不删；Nuitka 可增量生成 C/链接，改业务代码后重编更快。 |
| **不设 `--remove-output`** | 编完后保留中间目录，与上一条一致。 |
| **`NUITKA_CACHE_DIR`** | 脚本设为项目根 **`.nuitka-cache/`**（dll 依赖分析等）。 |
| **ccache + MinGW gcc** | 若 `ccache` 在 `PATH` 中，Nuitka Scons 阶段会走 `ccache gcc ...`；缓存目录多在 **`NUITKA_CACHE_DIR` 下的 `ccache`**（与「用户目录全局 ccache」可能并存，以 `ccache -s` 为准）。 |

### 8.3 大依赖与 post 拷贝

- **`--nofollow-import-to`**：numpy、paddle、cv2、playwright 等大块依赖**不整库编译**，编完后由 **`copy_nofollow_runtime_packages()`** 从当前 venv 的 `Lib\site-packages` 拷入 `dist/gui.dist/`。
- **带 `*.libs` 的 wheel（Windows DLL）**：与 **`numpy.libs`** 同理，须同时拷 **`scipy.libs`、`shapely.libs`、`pandas.libs`**，否则 `.pyd` 导入报「找不到指定模块」类错误。
- **pandas 旁路依赖**：除 **`pandas`、`pandas.libs`** 外，还须 **`pytz`、`dateutil`**（`python-dateutil` 的安装目录名）。
- **protobuf / setuptools 等**：同样通过拷包 + 可选 `.dist-info` 满足 `importlib.metadata`。
- **paddle 附属包（目录 + 顶层 .py）**：`paddlepaddle` 在 pip 中声明 **`astor`、`decorator`、`httpx`、`networkx`、`opt-einsum`、`typing-extensions`** 等；另有 **`httpx` 的传递依赖**（`httpcore`、`anyio`、`certifi`、`h11`、`idna` 等）。这些均不在 `paddle/` 目录内，nofollow 后须由 **`_PADDLE_SATELLITE` / `_PADDLE_SATELLITE_FILES`** 拷入 `gui.dist`（`decorator`、`typing_extensions`、`six` 常为单文件 wheel）。
- **scikit-image**：`lazy_loader`、`imageio`、`packaging`、`tifffile`、`pywt` 等须与 **`skimage`** 一并 post 拷贝（见脚本中 `_PADDLE_SATELLITE`）。
- **paddleocr（pip 声明）**：如 **`imgaug`、`tqdm`、`bs4`、`lxml`、`fitz`（PyMuPDF）、`docx`、`pdf2docx`** 等，已并入同一套 post 列表；升级 `paddleocr` 后若遇新 `ModuleNotFoundError`，对照 **`pip show paddleocr`** 补目录名。
- **标准库 `wave`**：构建命令含 **`--include-module=wave`**，post 阶段 **`copy_stdlib_wave()`** 可再补拷 **`Lib/wave.py`**（与增量未重编时兼容）。
- **pypinyin 数据文件**：构建含 **`--include-package-data=pypinyin`**，post 阶段 **`copy_pypinyin_package_data()`** 将 **`pinyin_dict.json`、`phrases_dict.json`** 拷至 **`gui.dist/pypinyin/`**（运行时按包路径读取）。
- **`distutils`**：**不要** `--include-package=distutils`（会与 `setuptools._distutils` 同编触发 Nuitka `duplicate locals`）。使用 **`--nofollow-import-to=distutils`**，编完后 **`copy_stdlib_distutils()`** 从 **`sysconfig.get_path('stdlib')/distutils`**（即与 `base_prefix` 对齐的标准库，**不是** venv 的 `Scripts\..\Lib`）拷入 `gui.dist`；若误用 venv 的 `Lib\distutils`，会因目录不存在而跳过，运行时报 `No module named 'distutils'`。

### 8.4 运行时数据目录（编译产物）

- 数据根目录为 **`dist\data`**（`config.json`、`profiles/`、`assets/`、`custom_task/`、`battle_character/` 等由 **`collect_data()`** 从仓库模板拷入；**`accounts/` 仅空目录**，不打包 `data/accounts/*.json`）。
- **`AutoScriptor.utils.paths`**：`is_compiled()` 须能识别打包环境（`__compiled__ in globals()`，并对 **`autoscriptor-engine.exe`** 名称兜底），否则误把 `gui.dist` 当成数据根。

### 8.5 与「安装包」的关系

- **`dist/gui.dist/autoscriptor-engine.exe` + `dist/data`** 即**可运行的引擎 + 用户数据**；不装 Electron 也可在浏览器访问 WebUI（端口与本地开发时一致，见 WebUI 服务端配置）。
- **Electron / NSIS**：`build_release.py` 不加 `--skip-electron` 时会跑 `electron-builder`，属**可选**分发形态，不是引擎能否运行的前提。

---

## 九、验收清单（怎样算「打包成功」）

1. **构建阶段**：`scripts/build_release.py` **进程退出码为 0**；日志中出现 **`[nuitka] 编译完成!`**、post 拷贝与 **`[data] 数据收集完成!`**。
2. **产物存在**：`dist/gui.dist/autoscriptor-engine.exe` 与 `dist/data/` 下有所需配置与资源。
3. **运行阶段**：在资源管理器中进入 `dist/gui.dist` 双击 exe，或命令行启动；能拉起服务并在浏览器打开 **`http://127.0.0.1:<端口>`**（默认多为 5000），无启动即崩溃。
4. **（可选）安装包**：仅当需要安装程序时，再验证 Electron 构建产物；失败时先独立排查 **引擎 exe**。

若第 1 步失败，以终端**完整报错**与（如有）**`nuitka-crash-report.xml`** 为准继续排错；若第 1 步通过而第 3 步失败，多为**运行时缺模块**或**数据路径**，对照第八节与 `build_release.py` 中的拷包列表。

若日志出现 **`[Errno 10048]`**（Windows：仅允许每个套接字地址使用一次），表示 **WebUI 端口已被占用**（例如本机已开另一实例、或 `npm start` 占用了 5000）。关闭占用进程或修改 `gui.py` / 配置中的监听端口后再试，与 Nuitka 打包是否成功无关。
