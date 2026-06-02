# Nuitka 资料与排错备忘（AutoScriptor 发行构建）

本文汇总官方文档与社区中**与 Windows / standalone / 排错**相关的入口，并记录本仓库在集成 Nuitka 时的实践结论。链接均为完整 URL，便于直接打开。

**整条发行流水线**（`build_release.py`、`backend.zip`、Electron portable/NSIS、增量缓存、安装向导）见 [build-and-run.md](./build-and-run.md)；**本文**侧重 Nuitka 选项与 post 拷贝，避免与上文重复。

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

日常运行方式（Electron、`npm start`）与构建命令的**对外备忘**见 [build-and-run.md](./build-and-run.md)；本节偏 Nuitka 与 post 拷贝细节。

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

- **`--nofollow-import-to`**：numpy、paddle、cv2 等大块依赖**不整库编译**，编完后由 **`copy_nofollow_runtime_packages()`** 从当前 venv 的 `Lib\site-packages` 拷入 `dist/gui.dist/`。
- **带 `*.libs` 的 wheel（Windows DLL）**：与 **`numpy.libs`** 同理，须同时拷 **`scipy.libs`、`shapely.libs`、`pandas.libs`**，否则 `.pyd` 导入报「找不到指定模块」类错误。
- **pandas 旁路依赖**：除 **`pandas`、`pandas.libs`** 外，还须 **`pytz`、`dateutil`**（`python-dateutil` 的安装目录名）。
- **protobuf / setuptools 等**：同样通过拷包 + 可选 `.dist-info` 满足 `importlib.metadata`。
- **paddle 附属包（目录 + 顶层 .py）**：`paddlepaddle` 在 pip 中声明 **`astor`、`decorator`、`httpx`、`networkx`、`opt-einsum`、`typing-extensions`** 等；另有 **`httpx` 的传递依赖**（`httpcore`、`anyio`、`certifi`、`h11`、`idna` 等）。这些均不在 `paddle/` 目录内，nofollow 后须由 **`_PADDLE_SATELLITE` / `_PADDLE_SATELLITE_FILES`** 拷入 `gui.dist`（`decorator`、`typing_extensions`、`six` 常为单文件 wheel）。
- **scikit-image**：`lazy_loader`、`imageio`、`packaging`、`tifffile`、`pywt` 等须与 **`skimage`** 一并 post 拷贝（见脚本中 `_PADDLE_SATELLITE`）。
- **paddleocr（pip 声明）**：如 **`imgaug`、`tqdm`、`bs4`、`lxml`、`fitz`（PyMuPDF）、`docx`、`pdf2docx`** 等，已并入同一套 post 列表；升级 `paddleocr` 后若遇新 `ModuleNotFoundError`，对照 **`pip show paddleocr`** 补目录名。
- **标准库 runtime helpers**：`collections`、`_collections_abc`、`ctypes` 是源码 overlay 例外，必须通过源码 stdlib runner 编译，并显式 `--include-package=collections` / `--include-module=_collections_abc` / `--include-package=ctypes`；否则嵌入式 `python310.zip/*.pyc` 会让 Nuitka 生成 namespace 空壳，抢占真实 `Lib` 目录，导致 `from collections import deque` 或 `ctypes.c_longlong` 失败。`contextlib`、`inspect`、`json`、`wave` 等较大 stdlib 面仍保持 **`--nofollow-import-to` + post 拷贝**，但 `multiprocessing` 是 post-copy-only：它需要 copied package 供 `Manager` / `Process` 使用，但不能加入 `--nofollow-import-to`，否则会和 Nuitka 的 multiprocessing 插件决策冲突。Windows stdlib `.pyd`（如 `pyexpat.pyd`、`_ssl.pyd`、`_overlapped.pyd`）和伴随 DLL（如 `libssl-1_1.dll`、`libcrypto-1_1.dll`、`libffi-7.dll`、`sqlite3.dll`）必须由 post 阶段成组补拷；`gui.py` 启动期会修正 `importlib` search locations、预载 `importlib._abc` / `importlib._common`，并清理 broken `multiprocessing` shell，避免 copied stdlib 被 Nuitka namespace 抢占。
- **pypinyin 数据文件**：构建含 **`--include-package-data=pypinyin`**，post 阶段 **`copy_pypinyin_package_data()`** 将 **`pinyin_dict.json`、`phrases_dict.json`** 拷至 **`gui.dist/pypinyin/`**（运行时按包路径读取）。
- **`distutils`**：**不要** `--include-package=distutils`（会与 `setuptools._distutils` 同编触发 Nuitka `duplicate locals`）。使用 **`--nofollow-import-to=distutils`**，编完后 **`copy_stdlib_distutils()`** 从 **`sysconfig.get_path('stdlib')/distutils`**（即与 `base_prefix` 对齐的标准库，**不是** venv 的 `Scripts\..\Lib`）拷入 `gui.dist`；若误用 venv 的 `Lib\distutils`，会因目录不存在而跳过，运行时报 `No module named 'distutils'`。

### 8.3.1 `importlib.metadata` bootstrap 经验

`importlib.metadata` 是 packaged runtime 的高风险点：`urllib3`、`pydantic`、`setuptools`、`paddle` 等都会间接依赖 `version()`、`distributions()`、`EntryPoints`。

- 不要用 `ModuleSpec(loader=None)` 加手动 `compile/exec` 载入 copied stdlib package。Nuitka 编译运行时下，这会让 `from . import _adapters` 等包内相对导入落到半初始化 package，最终出现 `cannot import name 'version' from importlib.metadata`、`module 'importlib.metadata' has no attribute 'distributions'` 或 `EntryPoints`。
- `gui.py` 的 copied stdlib 载入必须使用 `importlib.util.spec_from_file_location()`、`module_from_spec()`、`spec.loader.exec_module(module)`，并为 package 传入 `submodule_search_locations`。
- `importlib` 包修复期间不要再现场导入 `importlib.util`。如果先把 copied `importlib/` 加进 `importlib.__path__`，再 `from importlib.util import ...`，会加载 copied `util.py`；而 `util.py` 需要 `importlib._abc`，会形成启动期循环，表现为 `No module named 'importlib._abc'`，随后 `importlib.metadata` 半初始化。应在修改 `importlib.__path__` 前缓存 `spec_from_file_location` / `module_from_spec`。
- 普通解释器 direct probe 不能证明 Nuitka 编译入口的顶部缓存也成功。`dist/gui.dist/importlib` 会在 compiled runtime 启动早期参与解析，可能让顶部 `importlib.util` 缓存失败；`gui.py` 必须保留不依赖 `importlib.util` 的 `SourceFileLoader`/`ModuleSpec` 兜底来预载 `importlib._abc`，再加载 `importlib.metadata`。测试应覆盖把 cached helper 置空后的兜底路径。
- `importlib.metadata` 的 `__init__.py` 会立即执行 `from . import _adapters, _meta` 以及后续 helper 导入。compiled runtime 中包内相对导入可能仍撞上 Nuitka namespace/半初始化对象，所以载入 `importlib.metadata` 包前要按依赖顺序预载 `metadata` helper 子模块（`_functools`、`_text`、`_adapters`、`_collections`、`_itertools`、`_meta`）。
- `importlib.resources` 也不是单文件依赖。`resources.py` 会经 `_common.py` 调到 `importlib.readers`；若只预载 `resources.py`，`certifi.where()` / `requests` 在 smoke 中会报 `No module named 'importlib.readers'`。启动修复必须把 `importlib.readers` 与 `importlib.resources` 同组预载，并在失败时清理半初始化子模块。
- `encodings` 在 standalone 启动时可能已有一个可用但搜索路径不完整的 package；即使 `gui.dist/encodings/idna.py` 存在，`requests.models` 仍可能报 `No module named 'encodings.idna'`。启动修复要把 copied `encodings/` 挂到 `encodings.__path__` 和 `__spec__.submodule_search_locations`，并预载 `encodings.idna`。
- `multiprocessing` 若被 Nuitka 留成无 `__file__`/`__path__` 的 namespace shell，只删除壳还不够；`paddle` 会执行 `from multiprocessing import Manager, Process`，因此 compiled 启动期要把 copied stdlib `multiprocessing/__init__.py` 载成真实 package。不要为此添加 `--nofollow-import-to=multiprocessing`：Nuitka 可能报 `Conflict between user and plugin decision for module 'multiprocessing'`。若产物里已有 `multiprocessing/context.py` 但 smoke 仍报 `cannot import name 'context' from 'multiprocessing'`，说明 compiled runtime 留下了半初始化 `multiprocessing*` 状态；启动修复要先清理整棵 `sys.modules`，再优先用 frozen `SourceFileLoader` 载入 package。
- source-mode direct probe 能加载 copied `multiprocessing` 不代表 compiled smoke 会通过。Nuitka 4.x 会把 `multiprocessing` 本体编成只含 `__path__` 的 namespace package，并启用 `multiprocessing-preLoad` / `multiprocessing-postLoad` 插件钩子；直接执行 copied `__init__.py` 可能在 `context -> process/reduction -> context` 窗口失败。启动修复应先建立 copied 父包壳，预载并挂载 copied `multiprocessing.process` 与 `multiprocessing.util`，再加载 copied `context`；加载每个子模块时都要先挂到父包属性，最后从 `multiprocessing.context._default_context` 导出 `Manager`、`Process`、`Event` 等 API，避免依赖 copied `__init__.py` 的整包执行顺序。若 stderr 报 `cannot import name 'process' from 'multiprocessing'` 或 smoke 报 `No module named 'multiprocessing.util'`，优先检查这个预载顺序，而不是继续追加 copy 规则。
- `--runtime-import-smoke` 只覆盖导入面，`engine --electron` 启动还会创建 `multiprocessing.Event()` 和 `Process()`。`Event()` 会经 `context._default_context.Event()` 懒加载 `multiprocessing.synchronize`；若启动报 `No module named 'multiprocessing.synchronize'`，应在 engine 创建 `Event` 前预载并挂载 copied `synchronize`，并让测试实际调用 `Event()`。
- Windows 上 `Process.start()` 会沿 `context.SpawnProcess._Popen()` 懒加载 `multiprocessing.popen_spawn_win32`，并依赖 `reduction` / `spawn`。若 `engine --electron` 启动报 `No module named 'multiprocessing.popen_spawn_win32'`，应在导出默认上下文 API 到父包后，预载并挂载 copied `multiprocessing.reduction`、`multiprocessing.spawn`、`multiprocessing.popen_spawn_win32`；`spawn.py` 会从父包导入 `get_start_method` / `set_start_method`，不能在父包 API 导出前加载。测试要覆盖启动路径而不是只检查 `Process` 属性。
- 当上述 Windows spawn 路径开始工作后，packaged `engine --electron` 会让 `multiprocessing` 用当前 `autoscriptor-engine.exe -c ... --multiprocessing-fork` 启动子进程；Nuitka 默认的 self-execution deployment guard 会报 `program tried to call itself with '-c' argument` 并导致 WebUI smoke 超时。`scripts/build_release.py` 必须保留 `--no-deployment-flag=self-execution`，这是 WebUI worker 生命周期需求，不是隐私、端口或缺拷贝文件问题。
- 解除 self-execution guard 后还要确认 spawn 命令线形态。若任务管理器/WMI 显示大量 `autoscriptor-engine.exe`，但命令线是 `dist\gui.dist\python.exe -S -s -c "from multiprocessing.spawn import spawn_main..."`，说明 compiled runtime 没被 `multiprocessing` 识别为 frozen，子进程没有进入 `freeze_support()`，而是递归执行 `gui.py` 主循环。`gui.py` 必须在 `ensure_single_instance()` 之前设置 packaged `sys.frozen = True`、用 `GetModuleFileNameW(NULL)` 恢复真实 exe 到 `sys.executable`，并立即调用 `multiprocessing.freeze_support()`；验证前先清理递归进程，不能靠增加 smoke timeout。
- WebUI worker 真正进入 Uvicorn 后还会走 `uvicorn._subprocess -> multiprocessing.allow_connection_pickling()`。若此时出现 `cannot import name 'connection' from 'multiprocessing'`，不要继续检查 `connection.py` 是否拷贝；它通常已经在 `gui.dist/multiprocessing/`。应在 packaged multiprocessing bootstrap 导出默认上下文 API 后预载 `multiprocessing.connection`，因为 `connection.py` 需要父包上的 `AuthenticationError` / `BufferTooShort` 和 `context.reduction`。
- `typing.py` 与 copied `_collections_abc` 的组合可能让 Starlette 的 `Protocol` 基类检查失败，表现为 `Protocols can only inherit from other protocols, got <class '_collections_abc.Awaitable'>`。这是 packaged-only stdlib 组合问题，应在启动期确认 `typing._PROTO_ALLOWLIST["collections.abc"]` 和 `typing._PROTO_ALLOWLIST["_collections_abc"]` 至少允许 `Awaitable`、`AsyncIterator`、`AsyncIterable`、`Coroutine`、`Generator`、`Iterable`、`Iterator`、`Reversible`、`Sized`、`Container`、`Collection`、`Callable`、`ContextManager`、`AsyncContextManager`。
- exec 失败时要同时清理 `sys.modules[name]`、`name.*` 子模块以及父模块上的属性，避免下一次 import 复用半初始化对象。
- 修复后先跑便宜验证，再跑长构建：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m py_compile gui.py test\test_webui_contracts.py
.\.venv\Scripts\python.exe -X utf8 -m unittest `
  test.test_webui_contracts.TestInstallerContract.test_release_build_accepts_embedded_python_pyc_stdlib `
  test.test_webui_contracts.TestInstallerContract.test_release_build_prefers_source_stdlib_for_nuitka_collections `
  test.test_webui_contracts.TestInstallerContract.test_release_packaging_has_verification_and_optional_signing
```

已存在 `dist/gui.dist/importlib` 时，可先做 direct probe，但它不能替代完整 Nuitka rebuild 和 packaged runtime smoke：

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import os, sys, gui; exe=os.path.abspath('dist/gui.dist'); [sys.modules.pop(k, None) for k in list(sys.modules) if k == 'importlib.metadata' or k.startswith('importlib.metadata.')]; gui._bootstrap_packaged_importlib(exe); import importlib.metadata as m; print(hasattr(m,'version'), hasattr(m,'distributions'), hasattr(m,'EntryPoints'))"
```

完整发布构建仍必须看到 `autoscriptor-engine.exe --runtime-import-smoke` 通过，才能继续打 Electron 和更新包。

### 8.4 运行时数据目录（编译产物）

- 数据根目录为 **`dist\data`**。当前 **`collect_data()`** 会写入：
  - `config template.json`，并复制为发行版默认 `config.json`；
  - 空 `accounts/`，绝不打包 `data/accounts/*.json`；
  - `battle_character/`、`custom_task/`，忽略 `__pycache__` 和 `*.pyc/*.pyo`；
  - `assets/config/`、`assets/pic/`；
  - 空 `logs/` 占位。
- `ZmxyOL/assets/profiles/*.yaml` 只保留兼容路径说明，不再由 `collect_data()` 打入发行数据根；当前战斗职业逻辑以 `data/battle_character/` 为准。
- **`AutoScriptor.utils.paths`**：`is_compiled()` 须能识别打包环境（`__compiled__ in globals()`，并对 **`autoscriptor-engine.exe`** 名称兜底），否则误把 `gui.dist` 当成数据根。

### 8.5 与「安装包」的关系

- **`dist/gui.dist/autoscriptor-engine.exe` + `dist/data`** 即**可运行的引擎 + 用户数据**；不装 Electron 也可在浏览器访问 WebUI（端口与本地开发时一致，见 WebUI 服务端配置）。
- **Electron / NSIS**：`build_release.py` 不加 `--skip-electron` 时会跑 `electron-builder`，属**可选**分发形态，不是引擎能否运行的前提。

---

## 九、验收清单（怎样算「打包成功」）

1. **构建阶段**：`scripts/build_release.py` **进程退出码为 0**；日志中出现 **`[nuitka] 编译完成!`**、post 拷贝与 **`[data] 数据收集完成!`**。
2. **产物存在**：`dist/gui.dist/autoscriptor-engine.exe` 与 `dist/data/` 下有所需配置与资源。
3. **packaged runtime smoke**：`build_release.py` 自动运行 `autoscriptor-engine.exe --runtime-import-smoke`；必须通过，尤其要覆盖 `importlib.metadata`、`collections`、`ctypes`、`multiprocessing`、WebUI routes、NemuIpc 和 OCR 入口。
4. **运行阶段**：在资源管理器中进入 `dist/gui.dist` 双击 exe，或命令行启动；能拉起服务并在浏览器打开 **`http://127.0.0.1:<端口>`**（默认多为 5000），无启动即崩溃。
5. **（可选）安装包**：仅当需要安装程序时，再验证 Electron 构建产物；失败时先独立排查 **引擎 exe**。

若第 1 步失败，以终端**完整报错**与（如有）**`nuitka-crash-report.xml`** 为准继续排错；若第 1 步通过而第 3 步失败，多为**运行时缺模块**或**数据路径**，对照第八节与 `build_release.py` 中的拷包列表。

若日志出现 **`[Errno 10048]`**（Windows：仅允许每个套接字地址使用一次），表示 **WebUI 端口已被占用**（例如本机已开另一实例、或 `npm start` 占用了 5000）。关闭占用进程或修改 `gui.py` / 配置中的监听端口后再试，与 Nuitka 打包是否成功无关。

