"""
AutoScriptor 商业发行版构建脚本
================================
用法:
  python scripts/build_release.py [--clean] [--skip-nuitka] [--skip-electron] [-j N]
  桌面端默认: 单文件 portable（AutoScriptor_Zao_Install_<version>.exe），仅作 HTML 安装向导；
  安装完成后在安装目录写入 造笔.exe 作为日常启动器。
  可选: --electron-nsis（系统 NSIS） / --electron-zip（文件夹 zip） / --electron-nsis-fast-install

产物模式（保留两种）:
  - 默认: Nuitka + dist/data + portable 单 exe（内嵌 backend.zip）→ 用户只发一个安装包；首次运行打开 **installer.html** 解压引擎并校验 MuMu/ADB。
  - --skip-electron: 仅引擎 + data，不生成 Electron 包（便于只测引擎或浏览器访问）。

增量编译（默认）:
  - 不删除 dist/gui.build，Nuitka 可复用已生成的 C 目标文件，改业务代码后重编明显更快。
  - 不使用 --remove-output，编译结束后保留中间目录（与增量一致）。
  - 设置环境变量 NUITKA_CACHE_DIR 为项目下 .nuitka-cache/（dll/ccache 等缓存）。

完整清理（冷编译，最慢）:
  - 加 --clean：额外删除 dist/gui.build，依赖或 Nuitka 大版本升级、异常缓存时可使用。

流程:
  1. Nuitka standalone 编译 Web 后端入口（见脚本内入口路径）-> dist/gui.dist/
  2. 收集用户数据文件到 dist/data/
  3. 将 gui.dist 打成 dist/backend.zip（Electron 随包携带，首次运行由应用内向导解压到用户目录）
  4. (可选) --incremental-backend-from 上一版 gui.dist 或 backend.zip → dist/backend_incremental.zip（仅变更文件，供已安装用户小体积升级）
  5. (可选) electron-builder 打包（默认 portable 单 exe；--electron-nsis / --electron-zip 见 --help）

用户文档（参数、产物形态、缓存、排错）:
  docs/AutoScriptor/release/build-and-run.md

打包前（推荐，约数秒，避免白等 20+ 分钟 Nuitka）::

  .venv-nuitka\\Scripts\\python.exe scripts\\verify_packaging_prereqs.py

前置条件:
  - Python 3.10 + .venv 已激活
  - pip install nuitka ordered-set zstandard
  - MinGW64 或 MSVC C 编译器已安装
  - Node.js + npm (用于 electron-builder)
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import sysconfig
import time
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 目录分工（互不混用、默认互不覆盖）:
# - dist/        : Nuitka 输出 gui.dist、collect_data、license；clean() 只动这些子目录与 dist/gui.build。
# - dist_electron/: 仅 electron-builder 写入；clean() 从不删除，避免冲掉安装包产物。
DIST_DIR = PROJECT_ROOT / "dist"
NUITKA_OUT = DIST_DIR / "gui.dist"
DATA_DIR = DIST_DIR / "data"
LICENSE_DIR = DIST_DIR / "license"
DIST_ELECTRON_DIR = PROJECT_ROOT / "dist_electron"
# 项目内 Nuitka 总缓存根（dll 依赖分析、字节码等；与 gui.build 内 C 增量不同，二者都保留可显著提速）
NUITKA_USER_CACHE = PROJECT_ROOT / ".nuitka-cache"


def _format_duration(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.2f}h"
    if seconds >= 60:
        return f"{seconds / 60:.2f}min"
    return f"{seconds:.2f}s"


@contextmanager
def timed_step(timings: list[tuple[str, float]], name: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        timings.append((name, time.perf_counter() - t0))


def _print_incremental_cache_status(args: argparse.Namespace) -> None:
    """构建开始前提示 Nuitka 增量目录与常用加速组合，避免误用 --clean 导致 1h+ 冷编。"""
    gb = DIST_DIR / "gui.build"
    gd = NUITKA_OUT
    if args.clean:
        print(
            "[build] 已指定 --clean：将删除 dist/gui.build，本次为冷编译（通常最慢；"
            "日常迭代请勿加此参数）。"
        )
    elif gb.is_dir():
        print(
            "[build] 增量: dist/gui.build 已保留，Nuitka 可复用已生成的 C 目标（改少量源码时明显快于冷编）。"
        )
    else:
        print("[build] dist/gui.build 不存在：本次 Nuitka 将接近全量/首次编译，耗时较长。")
    if NUITKA_USER_CACHE.is_dir():
        print(f"[build] Nuitka 缓存目录存在: {NUITKA_USER_CACHE}（dll/依赖分析等）")
    if args.skip_nuitka:
        if gd.is_dir():
            print("[build] --skip-nuitka：沿用现有 dist/gui.dist，不重新跑 Nuitka。")
        else:
            print("[build] 警告: --skip-nuitka 但 dist/gui.dist 不存在，后续打包会失败。")
    if args.skip_electron:
        print("[build] --skip-electron：跳过 backend.zip 与 electron-builder（仅引擎 + data）。")
    if not args.clean and not args.skip_nuitka and not args.skip_electron:
        print(
            "[build] 加速: 只改 Python 可加 --skip-electron；只改 webapp 可先完整编一次再 "
            "`--skip-nuitka`（需已有 gui.dist）。"
        )


def _print_build_timings(timings: list[tuple[str, float]], wall_total: float) -> None:
    """构建结束后打印各步骤耗时与合计（各步之和可能略小于 wall，因未计间隔开销）。"""
    print()
    print("[build] 耗时统计")
    print("-" * 60)
    step_sum = 0.0
    for name, sec in timings:
        step_sum += sec
        print(f"  {name}: {_format_duration(sec)}")
    print("-" * 60)
    print(f"  各步骤合计: {_format_duration(step_sum)}")
    print(f"  总耗时 (wall): {_format_duration(wall_total)}")
    print("-" * 60)


def _rmtree_onerror(func, path, _exc_info):
    """Windows 下只读文件会导致 rmtree 失败，先去掉只读再重试。"""
    try:
        if os.path.exists(path):
            os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _rmtree_robust(path: Path) -> None:
    """删除目录树。Windows 上 dist/gui.dist 易被引擎/杀软/资源管理器占用（WinError 32），带重试。"""
    p = str(path)
    if os.name != "nt":
        shutil.rmtree(p)
        return
    last: OSError | None = None
    for attempt in range(1, 9):
        try:
            shutil.rmtree(p, onerror=_rmtree_onerror)
            return
        except OSError as e:
            last = e
            err = getattr(e, "winerror", None) or getattr(e, "errno", 0)
            if err not in (32, 13):
                raise
            if attempt < 8:
                time.sleep(0.3 * attempt)
    assert last is not None
    print(
        "[clean] 无法删除目录（仍被占用）: "
        f"{path}\n"
        "  请关闭：正在运行的 AutoScriptor/造笔、本机 Python 调试、"
        "占用该目录的终端/IDE，或暂时排除杀软后再试。"
    )
    raise last


def clean(full: bool = False, skip_nuitka: bool = False):
    """清理旧构建产物。

    full=False（默认）: 保留 dist/gui.build，便于 Nuitka 增量编译。
    full=True: 同时删除 gui.build，相当于冷编译。

    skip_nuitka=True 时不删除 dist/gui.dist（仅打 Electron 时须保留已有引擎目录）。

    不删除 dist_electron/：与 dist/ 分离，避免与 Nuitka/data 清理互相覆盖。
    """
    dirs = [DATA_DIR, LICENSE_DIR]
    if not skip_nuitka:
        dirs.insert(0, NUITKA_OUT)
    for d in dirs:
        if d.exists():
            _rmtree_robust(d)
            print(f"[clean] 已删除 {d}")
    build_dir = DIST_DIR / "gui.build"
    if full:
        if build_dir.exists():
            _rmtree_robust(build_dir)
            print(f"[clean] 已删除 {build_dir}（完整清理）")
    else:
        if build_dir.exists():
            print(f"[clean] 保留 {build_dir}（增量编译；需冷编请加 --clean）")


def warn_if_embedded_style_venv() -> None:
    """嵌入式 Python 创建的 venv 常使 base_prefix 指向 .venv\\Scripts；在此环境下 Nuitka 虽可能编译成功，
    但 standalone 运行时易出现 encodings 缺失。见 docs/AutoScriptor/release/nuitka-reference.md 第六节。
    """
    bp = Path(getattr(sys, "base_prefix", sys.prefix)).resolve()
    if os.name == "nt" and bp.name.lower() == "scripts":
        print(
            "[nuitka] 警告: 当前解释器 base_prefix 指向 Scripts 子目录，疑似「嵌入式 Python + venv」。"
        )
        print(
            "[nuitka] 若编译产物启动报 No module named 'encodings'，请改用 python.org 完整安装版 Python 3.10 新建 venv 后重试。"
        )


def ensure_windows_python_dev_files() -> None:
    """Nuitka Scons 阶段需要在 getSystemPrefixPath() 下找到 include/Python.h 与 libs/python310.lib。

    嵌入式 Python 创建的 venv 常将 base_prefix 指向 .venv\\Scripts，须在该目录补齐开发文件。
    详见 docs/AutoScriptor/release/nuitka-reference.md
    """
    if os.name != "nt":
        return
    base = Path(getattr(sys, "base_prefix", sys.prefix)).resolve()
    py_h = base / "include" / "Python.h"
    # 与 Nuitka addWin32PythonLib 一致: python + abi 去点 + .lib
    ver = f"{sys.version_info.major}{sys.version_info.minor}"
    lib = base / "libs" / f"python{ver}.lib"
    if py_h.is_file() and lib.is_file():
        return
    print("[nuitka] 缺少 Windows Python 开发文件，Scons 将无法找到 Python.h / .lib。")
    print(f"  期望: {py_h}")
    print(f"  期望: {lib}")
    print("  请从 python.org 完整安装或 NuGet python 包复制 tools/include 与 tools/libs 到上述前缀，")
    print("  或见 docs/AutoScriptor/release/nuitka-reference.md 中「嵌入式 Python」一节。")
    sys.exit(1)


def ensure_python_minus_s_disables_site() -> None:
    """Fail fast if Nuitka's ``python -S`` re-exec would not disable site.

    Some embedded-style Python distributions force ``import site`` from
    ``pythonXY._pth``. Nuitka starts a clean compiler process with ``-S``; if
    that still leaves ``sys.flags.no_site`` false, Nuitka can repeatedly
    restart itself and create an unbounded process chain.
    """
    probe = subprocess.run(
        [sys.executable, "-S", "-c", "import sys; print(int(sys.flags.no_site))"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    out = ((probe.stdout or "") + (probe.stderr or "")).strip()
    if probe.returncode != 0 or out.splitlines()[:1] != ["1"]:
        print("[nuitka] 错误: 当前 Python 的 `-S` 不能真正禁用 site，Nuitka 可能无限重启自身。")
        print(f"[nuitka] 解释器: {sys.executable}")
        if out:
            print(f"[nuitka] 探测输出: {out}")
        print("[nuitka] 请检查 pythonXY._pth / sitecustomize，移除强制 `import site` 后重试。")
        sys.exit(1)


# Heavy or highly dynamic third-party packages are nofollowed and copied from
# the pinned runtime venv after compilation. Project modules stay compiled, while
# framework/SDK wheels remain normal importable packages inside gui.dist.
_NUITKA_NOFOLLOW = [
    "numpy",
    "cv2",
    "PIL",
    "paddle",
    "paddleocr",
    "scipy",
    "torch",
    "tensorflow",
    "sklearn",
    "skimage",
    "shapely",
    "pyclipper",
    "lmdb",
    "openvino",
    "onnxruntime",
    "matplotlib",
    "pandas",
    "playwright",
    "requests",
    "urllib3",
    "charset_normalizer",
    "cryptography",
    "cffi",
    "pycparser",
    "Crypto",
    "onepush",
    "openai",
    "distro",
    "jiter",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "annotated_types",
    "annotated_doc",
    "uvicorn",
    "websockets",
    "tzdata",
    "click",
    "colorama",
    "yaml",
    "httpx",
    "httpcore",
    "anyio",
    "certifi",
    "h11",
    "idna",
    "sniffio",
]

_NUITKA_NOFOLLOW_ONLY = [
    "pip",
    "ensurepip",
    "rich",
    "pygments",
    "prompt_toolkit",
]

# nofollow 大包旁路：paddle 的 pip/httpx 依赖、skimage 的 pip 依赖等，须拷入 gui.dist。
# decorator、typing_extensions 常见为顶层单文件 wheel。
_PADDLE_SATELLITE = (
    "google",
    "setuptools",
    "pkg_resources",
    "astor",
    "httpx",
    "httpcore",
    "anyio",
    "certifi",
    "h11",
    "idna",
    "sniffio",
    "networkx",
    "opt_einsum",
    "lazy_loader",
    "imageio",
    "packaging",
    "tifffile",
    "pywt",
    "imgaug",
    # paddleocr pip 声明中、非 nofollow 顶层名的依赖（含 tqdm、beautifulsoup4→bs4、PyMuPDF→fitz 等）
    "attrdict",
    "bs4",
    "cython",
    "Cython",
    "fire",
    "fontTools",
    "lxml",
    "openpyxl",
    "pdf2docx",
    "premailer",
    "fitz",
    "docx",
    "rapidfuzz",
    "tqdm",
    "visualdl",
    # questionary is pulled by legacy CLI/config helpers exposed through AutoScriptor.__all__.
    "questionary",
    "prompt_toolkit",
    "pygments",
    "wcwidth",
    "exceptiongroup",
    "typing_inspection",
)
_PADDLE_SATELLITE_FILES = (
    "decorator.py",
    "typing_extensions.py",
    "six.py",
    "socks.py",
    "sockshandler.py",
)


def _copy_site_entry(sp: Path, dst_root: Path, name: str) -> None:
    """复制 venv site-packages 下的目录或顶层 .py 模块。"""
    src = sp / name
    if src.is_dir():
        shutil.copytree(src, dst_root / name, dirs_exist_ok=True)
        print(f"[post] {name}/ -> gui.dist/")
    elif src.is_file():
        shutil.copy2(src, dst_root / name)
        print(f"[post] {name} -> gui.dist/")
    else:
        print(f"[post] 跳过（不存在）: {src}")


def _copy_site_glob(sp: Path, dst_root: Path, pattern: str) -> None:
    """Copy top-level binary/helper files whose names include ABI tags."""
    matched = False
    for src in sp.glob(pattern):
        if src.is_file():
            shutil.copy2(src, dst_root / src.name)
            print(f"[post] {src.name} -> gui.dist/")
            matched = True
    if not matched:
        print(f"[post] 跳过（不存在）: {sp / pattern}")


def runtime_site_packages_root() -> Path | None:
    """Return the dependency site-packages used for nofollow runtime copies.

    Normal builds run from a venv, so sys.executable/../Lib/site-packages works.
    Some release machines compile with a full base Python and pass the venv
    packages through PYTHONPATH; support that explicitly so Nuitka gets a real
    stdlib while post-copy still uses the pinned project dependencies.
    """
    candidates: list[Path] = []
    explicit = os.environ.get("AUTOSCRIPTOR_RUNTIME_SITE_PACKAGES", "").strip()
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages")
    for raw in sys.path:
        if raw and raw.replace("\\", "/").lower().endswith("/site-packages"):
            candidates.append(Path(raw))
    seen: set[str] = set()
    for p in candidates:
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_dir():
            print(f"[post] site-packages: {resolved}")
            return resolved
    return None


def copy_nofollow_runtime_packages() -> None:
    """将 --nofollow-import-to 涉及的包从当前解释器 venv 的 site-packages 拷入 gui.dist。

    Nuitka 在 deployment 模式下不会把这些目录打进 standalone；复制后运行时 sys.path 即可加载 .pyd。
    """
    sp = runtime_site_packages_root()
    if sp is None:
        print("[post] 跳过：未找到 site-packages")
        return
    dst_root = NUITKA_OUT
    dst_root.mkdir(parents=True, exist_ok=True)

    folder_names: set[str] = set()
    for mod in _NUITKA_NOFOLLOW:
        if mod == "numpy":
            folder_names.update(("numpy", "numpy.libs"))
        elif mod == "scipy":
            folder_names.update(("scipy", "scipy.libs"))
        elif mod == "pandas":
            folder_names.update(("pandas", "pandas.libs", "pytz", "dateutil"))
        elif mod == "cv2":
            folder_names.add("cv2")
        elif mod == "PIL":
            folder_names.add("PIL")
        elif mod == "shapely":
            folder_names.update(("shapely", "shapely.libs"))
        else:
            folder_names.add(mod)

    for name in sorted(folder_names):
        src = sp / name
        if src.is_dir():
            dest = dst_root / name
            shutil.copytree(src, dest, dirs_exist_ok=True)
            print(f"[post] {name} -> gui.dist/")

    # rich：Nuitka 易漏带 _unicode_data 下「unicode17-0-0」等动态子模块，整包覆盖
    _copy_site_entry(sp, dst_root, "rich")

    # FastAPI/Starlette UploadFile 依赖 python-multipart；部分 Nuitka 版本 follow 后仍可能未进 standalone
    _copy_site_entry(sp, dst_root, "multipart")
    _copy_site_entry(sp, dst_root, "python_multipart")

    for extra in _PADDLE_SATELLITE:
        _copy_site_entry(sp, dst_root, extra)
    for fname in _PADDLE_SATELLITE_FILES:
        _copy_site_entry(sp, dst_root, fname)

    # cffi keeps the actual extension module at site-packages root.
    _copy_site_glob(sp, dst_root, "_cffi_backend*.pyd")
    _copy_site_entry(sp, dst_root, "_yaml")

    # 部分库的 importlib.metadata 依赖 .dist-info
    needles = (
        "numpy", "opencv", "pillow", "paddle", "scipy", "pandas", "matplotlib",
        "torch", "tensorflow", "sklearn", "skimage", "shapely", "pyclipper",
        "lmdb", "openvino", "onnx", "playwright", "rich", "protobuf", "setuptools",
        "pytz", "python-dateutil", "dateutil",
        "opt_einsum", "opt-einsum", "astor", "httpx", "httpcore", "anyio", "certifi",
        "h11", "idna", "sniffio", "networkx", "decorator", "typing_extensions",
        "typing-extensions", "lazy_loader", "imageio", "packaging", "tifffile",
        "pywavelets", "scikit-image", "scikit_image", "imgaug", "attrdict",
        "beautifulsoup", "tqdm", "pymupdf", "openpyxl", "pdf2docx", "premailer",
        "rapidfuzz", "visualdl", "python-docx", "lxml", "fire", "cython",
        "fonttools",
        "python_multipart", "requests", "urllib3", "charset-normalizer",
        "charset_normalizer", "cryptography", "cffi", "pycparser",
        "pycryptodome", "crypto", "onepush", "openai", "distro", "jiter",
        "fastapi", "starlette", "pydantic", "pydantic-core",
        "pydantic_core", "annotated-types", "annotated_types",
        "annotated-doc", "annotated_doc", "uvicorn", "websockets",
        "tzdata", "click", "colorama", "pyyaml",
        "questionary", "prompt-toolkit", "prompt_toolkit", "pygments", "wcwidth",
        "exceptiongroup", "typing-inspection", "typing_inspection",
    )
    for item in sp.iterdir():
        if not item.is_dir() or not item.name.endswith(".dist-info"):
            continue
        low = item.name.lower()
        if any(n in low for n in needles):
            dest = dst_root / item.name
            shutil.copytree(item, dest, dirs_exist_ok=True)
            print(f"[post] {item.name} -> gui.dist/")


def _nuitka_output_python_version() -> tuple[int, int] | None:
    """Infer the Python ABI used by an existing gui.dist from pythonXY.dll."""
    if not NUITKA_OUT.is_dir():
        return None
    for dll in NUITKA_OUT.glob("python*.dll"):
        match = re.fullmatch(r"python(\d)(\d{2})\.dll", dll.name.lower())
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def _venv_home_from_cfg() -> Path | None:
    cfg = PROJECT_ROOT / ".venv-nuitka" / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("home"):
                _, value = line.split("=", 1)
                home = Path(value.strip())
                return home if home.exists() else None
    except OSError:
        return None
    return None


def _python_home_version(home: Path) -> tuple[int, int] | None:
    exe = home / ("python.exe" if os.name == "nt" else "python")
    if not exe.is_file():
        return None
    try:
        out = subprocess.check_output(
            [str(exe), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        ).strip()
        major, minor = out.split(".", 1)
        return int(major), int(minor)
    except Exception:
        return None


def _stdlib_candidates() -> list[tuple[Path, tuple[int, int] | None, str]]:
    candidates: list[tuple[Path, tuple[int, int] | None, str]] = []
    seen: set[Path] = set()

    def add(path: Path, version: tuple[int, int] | None, label: str) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append((path, version, label))

    current_stdlib = Path(sysconfig.get_path("stdlib"))
    add(current_stdlib, (sys.version_info.major, sys.version_info.minor), "current interpreter")

    home = _venv_home_from_cfg()
    if home is not None:
        add(home / "Lib", _python_home_version(home), ".venv-nuitka home")

    base_prefix = Path(sys.base_prefix)
    add(base_prefix / "Lib", (sys.version_info.major, sys.version_info.minor), "sys.base_prefix")
    return candidates


def resolve_runtime_stdlib(required: tuple[str, ...]) -> Path:
    """Pick a stdlib matching gui.dist's Python ABI, especially for --skip-nuitka.

    A common failure mode is running --skip-nuitka with the host Python while
    reusing a Python 3.10 Nuitka engine. Copying 3.13 encodings into that tree
    can satisfy init_fs_encoding but crash the executable later. Treat a version
    mismatch as a build error, not a warning.
    """
    target = _nuitka_output_python_version() or (sys.version_info.major, sys.version_info.minor)
    skipped: list[str] = []
    for stdlib, version, label in _stdlib_candidates():
        missing = [name for name in required if not (stdlib / name).exists()]
        if missing:
            skipped.append(f"{label}: missing {', '.join(missing)} at {stdlib}")
            continue
        if version is not None and version != target:
            skipped.append(f"{label}: Python {version[0]}.{version[1]} != target {target[0]}.{target[1]} at {stdlib}")
            continue
        print(f"[post] stdlib source: {stdlib} ({label}, target Python {target[0]}.{target[1]})")
        return stdlib

    print("[post] 错误: 未找到与 gui.dist Python ABI 匹配的 stdlib。")
    for item in skipped:
        print(f"  - {item}")
    sys.exit(1)


def copy_stdlib_distutils() -> None:
    """将 CPython 标准库 Lib/distutils 拷入 gui.dist。

    setuptools.monkey 会 ``import distutils.*``，需与源码目录一致；若用 Nuitka 编译 distutils，
    会与 ``setuptools._distutils`` 中同名模块冲突（duplicate locals / distutils.version）。

    注意：venv 下 ``sys.executable`` 的上一级 ``Lib`` 通常只有 site-packages，**没有**标准库
    ``distutils``；必须从 ``sysconfig.get_path('stdlib')``（与 ``sys.base_prefix`` 对齐）取源。
    """
    stdlib = resolve_runtime_stdlib(("distutils",))
    src = stdlib / "distutils"
    dst_root = NUITKA_OUT
    if not src.is_dir():
        print(f"[post] 跳过 distutils：未找到 {src}（若 Python>=3.12 已无 stdlib distutils，需另案处理）")
        return
    dest = dst_root / "distutils"
    shutil.copytree(src, dest, dirs_exist_ok=True)
    print("[post] distutils/ (stdlib) -> gui.dist/")


def copy_stdlib_wave() -> None:
    """将 ``Lib/wave.py`` 拷入 gui.dist（与 ``--include-module=wave`` 二选一即可；增量未重编时可用于补拷）。"""
    stdlib = resolve_runtime_stdlib(("wave.py",))
    src = stdlib / "wave.py"
    dst_root = NUITKA_OUT
    dst_root.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dst_root / "wave.py")
        print("[post] wave.py (stdlib) -> gui.dist/")
        return

    embedded_zip = Path(sys.executable).resolve().parent / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    if embedded_zip.is_file():
        try:
            with zipfile.ZipFile(embedded_zip) as zf:
                if "wave.pyc" in zf.namelist():
                    (dst_root / "wave.pyc").write_bytes(zf.read("wave.pyc"))
                    print("[post] wave.pyc (python zip) -> gui.dist/")
                    return
        except (OSError, zipfile.BadZipFile) as e:
            print(f"[post] 读取 {embedded_zip} 失败: {e}")
    print(f"[post] 跳过 wave：未找到 {src} 或 {embedded_zip}!wave.pyc")


def copy_stdlib_runtime_helpers() -> None:
    """Copy stdlib modules imported by nofollowed source packages at runtime.

    Several large packages are copied as source instead of compiled by Nuitka
    (Paddle/PaddleOCR/scipy/skimage/requests). They perform optional imports
    deep inside their import graph, so a tiny hand-maintained stdlib list turns
    into whack-a-mole on clean Windows machines. Copy the small CPython Lib
    surface that is safe for runtime use, while excluding installers, venv
    tooling, and site-packages.
    """
    stdlib = resolve_runtime_stdlib(("site.py", "pydoc.py", "unittest"))
    dst_root = NUITKA_OUT
    excluded_dirs = {
        "__pycache__",
        "ensurepip",
        "idlelib",
        "site-packages",
        "test",
        "tkinter",
        "turtledemo",
        "venv",
    }
    excluded_files = {"__phello__.foo.py", "antigravity.py", "this.py"}
    copied_dirs = 0
    copied_files = 0
    for child in sorted(stdlib.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir():
            if child.name in excluded_dirs:
                continue
            shutil.copytree(child, dst_root / child.name, dirs_exist_ok=True)
            copied_dirs += 1
        elif child.is_file() and child.suffix == ".py" and child.name not in excluded_files:
            shutil.copy2(child, dst_root / child.name)
            copied_files += 1
    print(f"[post] stdlib runtime helpers -> gui.dist/ ({copied_dirs} dirs, {copied_files} files)")


def copy_stdlib_encodings() -> None:
    """CPython 启动阶段必须能导入 encodings；缺失时 clean Windows 会直接启动失败。"""
    stdlib = resolve_runtime_stdlib(("encodings",))
    src = stdlib / "encodings"
    dst_root = NUITKA_OUT
    if not src.is_dir():
        print(f"[post] 警告: 未找到 stdlib encodings: {src}")
        return
    dst = dst_root / "encodings"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print("[post] encodings/ (stdlib) -> gui.dist/")


def copy_pypinyin_package_data() -> None:
    """pypinyin 在运行时按 ``__file__`` 旁加载 ``*.json``；Nuitka 编译后须补拷数据文件。"""
    site_packages = runtime_site_packages_root()
    sp = site_packages / "pypinyin" if site_packages else Path()
    dst = NUITKA_OUT / "pypinyin"
    if not sp.is_dir():
        print(f"[post] 跳过 pypinyin 数据：未找到 {sp}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("pinyin_dict.json", "phrases_dict.json"):
        f = sp / name
        if f.is_file():
            shutil.copy2(f, dst / name)
            print(f"[post] pypinyin/{name} -> gui.dist/pypinyin/")


VC_RUNTIME_DLLS = (
    "msvcp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "concrt140.dll",
    "vcomp140.dll",
)


def _windows_system_runtime_dir() -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return system_root / ("System32" if sys.maxsize > 2**32 else "SysWOW64")


def ensure_vc_runtime_dlls() -> None:
    """Bundle VC++ runtime DLLs needed by binary wheels."""
    if os.name != "nt":
        return
    NUITKA_OUT.mkdir(parents=True, exist_ok=True)
    source_dir = _windows_system_runtime_dir()
    missing: list[str] = []
    for name in VC_RUNTIME_DLLS:
        dst = NUITKA_OUT / name
        if dst.is_file():
            continue
        candidates = [
            source_dir / name,
            Path(sys.executable).resolve().parent / name,
        ]
        copied = False
        for src in candidates:
            if src.is_file():
                shutil.copy2(src, dst)
                print(f"[post] {name} -> gui.dist/")
                copied = True
                break
        if not copied:
            missing.append(name)
    if missing:
        print(
            "[post] 警告: 未找到 VC++ 运行库 DLL，目标电脑若未安装 VC++ 2015-2022 Runtime "
            f"可能无法启动: {', '.join(missing)}"
        )


def ensure_python_stable_abi_dlls() -> None:
    """Bundle python3.dll for abi3 wheels such as modern cryptography."""
    if os.name != "nt":
        return
    NUITKA_OUT.mkdir(parents=True, exist_ok=True)
    candidates: list[Path] = []
    home = _venv_home_from_cfg()
    if home is not None:
        candidates.append(home)
    candidates.extend(
        [
            Path(getattr(sys, "base_prefix", sys.prefix)).resolve(),
            Path(sys.executable).resolve().parent,
        ]
    )
    for name in ("python3.dll",):
        dst = NUITKA_OUT / name
        if dst.is_file():
            continue
        for base in candidates:
            src = base / name
            if src.is_file():
                shutil.copy2(src, dst)
                print(f"[post] {name} -> gui.dist/")
                break
        else:
            print(f"[post] 警告: 未找到 {name}，abi3 扩展 wheel 可能无法加载")


def post_process_nuitka_output(timings: list[tuple[str, float]] | None = None) -> None:
    """Copy runtime packages and DLLs into gui.dist after compile or reuse."""
    t_post = time.perf_counter()
    copy_nofollow_runtime_packages()
    copy_stdlib_distutils()
    copy_stdlib_encodings()
    copy_stdlib_wave()
    copy_stdlib_runtime_helpers()
    copy_pypinyin_package_data()
    ensure_vc_runtime_dlls()
    ensure_python_stable_abi_dlls()
    if timings is not None:
        timings.append(("Nuitka 后处理 (拷包/补文件)", time.perf_counter() - t_post))


def run_nuitka(timings: list[tuple[str, float]] | None = None, jobs: int | None = None):
    """执行 Nuitka standalone 编译。

    jobs: 传给 Nuitka 的 ``--jobs``（C 编译并行数）；None 表示不写该选项，沿用 Nuitka 默认。
    """
    warn_if_embedded_style_venv()
    ensure_windows_python_dev_files()
    ensure_python_minus_s_disables_site()

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--no-deployment-flag=excluded-module-usage",
        f"--output-dir={DIST_DIR}",
        "--output-filename=autoscriptor-engine.exe",
        "--follow-import-to=AutoScriptor",
        "--follow-import-to=ZmxyOL",
        "--follow-import-to=services",
        "--include-package=AutoScriptor",
        "--include-package=ZmxyOL",
        "--include-package=services.core",
        "--include-package=services.webui",
        "--include-module=services.single_instance",
        # setuptools 依赖；仅复制 setuptools 目录时，冻结环境需能解析该子模块
        "--include-package=_distutils_hack",
        # 不可 --include-package=distutils：与 setuptools._distutils 同编会 Nuitka duplicate locals（见 crash report）
        # 运行时由 copy_stdlib_distutils() 从 Lib/distutils 拷入 gui.dist，并 nofollow 避免编译 stdlib distutils
        "--nofollow-import-to=distutils",
        # paddle.audio 等会 import wave；nofollow paddle 时静态分析易漏，显式纳入 standalone
        "--include-module=wave",
        # nofollowed runtime packages (requests/httpx/etc.) import these stdlib
        # packages dynamically; compiling the parent package avoids shadowing a
        # copied stdlib directory with a non-package frozen module.
        "--include-package=http",
        "--include-package=email",
        "--include-package=html",
        "--include-package=urllib",
        "--include-package=xml",
        "--include-package=xmlrpc",
        "--include-package=logging",
        "--include-package=asyncio",
        "--include-package=concurrent",
        "--include-package=json",
        "--include-package=unittest",
        "--include-package=pydoc_data",
        "--include-package=wsgiref",
        # FastAPI Form/UploadFile 依赖 python-multipart（import 名 multipart；另有顶层 python_multipart）。
        # 勿用 --include-package=multipart：Nuitka 4.x 在部分环境下 locateModule finding≠absolute 会 FATAL。
        # --follow-import-to 在判为 unused 时仍不打包；须 --include-module 强制纳入 standalone。
        "--include-module=multipart",
        "--include-module=python_multipart",
        # pypinyin 在包内旁加载 JSON；与 copy_pypinyin_package_data() 一并保证可运行
        "--include-package-data=pypinyin",
        "--include-data-dir=services/webui/static=services/webui/static",
        "--include-data-dir=services/webui/vendor=services/webui/vendor",
        # 不使用 --remove-output：保留 gui.build 供下次增量编译；否则每次删 build 目录无法复用 .o
        "--assume-yes-for-downloads",
        "--company-name=AutoScriptor",
        "--product-name=ZaoBi",
        "--file-version=1.0.0",
        "--product-version=1.0.0",
        "--show-progress",
        "--show-memory",
        str(PROJECT_ROOT / "gui.py"),
    ]
    for name in [*_NUITKA_NOFOLLOW, *_NUITKA_NOFOLLOW_ONLY]:
        cmd.insert(-1, f"--nofollow-import-to={name}")

    icon = PROJECT_ROOT / "webapp" / "buildResources" / "icon.ico"
    if icon.exists():
        cmd.insert(-1, f"--windows-icon-from-ico={icon}")
    if jobs is not None:
        cmd.insert(-1, f"--jobs={jobs}")

    NUITKA_USER_CACHE.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    prev = env.get("NUITKA_CACHE_DIR")
    env["NUITKA_CACHE_DIR"] = str(NUITKA_USER_CACHE.resolve())
    print("[nuitka] 开始编译 (大型依赖为 nofollow+拷包；增量时仅重编变更模块)...")
    print(f"[nuitka] NUITKA_CACHE_DIR={env['NUITKA_CACHE_DIR']}")
    if jobs is not None:
        print(f"[nuitka] 并行编译: --jobs={jobs}")
    if prev and prev != env["NUITKA_CACHE_DIR"]:
        print(f"[nuitka] 注意: 已覆盖原 NUITKA_CACHE_DIR={prev!r}")
    print("[nuitka] 命令:", " ".join(cmd[:8]), "...")
    t_nuitka = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    if timings is not None:
        timings.append(("Nuitka 编译 (subprocess)", time.perf_counter() - t_nuitka))
    if result.returncode != 0:
        print("[nuitka] 编译失败!")
        sys.exit(1)
    print("[nuitka] 编译完成!")
    post_process_nuitka_output(timings=timings)


def collect_data():
    """收集用户可编辑的数据文件到 dist/data/。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 发行包内 config.json 一律来自 config template.json，避免把打包机上的本地账号/路径带入新电脑。
    tpl = PROJECT_ROOT / "config template.json"
    dist_cfg = DATA_DIR / "config.json"
    dist_tpl = DATA_DIR / "config template.json"
    if tpl.exists():
        shutil.copy2(tpl, dist_tpl)
        shutil.copy2(tpl, dist_cfg)
        print("[data] config template.json -> data/config template.json")
        print("[data] config template.json -> data/config.json（避免携带打包机本地配置）")
    else:
        src_cfg = PROJECT_ROOT / "config.json"
        if src_cfg.exists():
            shutil.copy2(src_cfg, dist_cfg)
            print("[data] config.json（未找到模板，降级使用）")

    # accounts/：仅保留空目录，绝不把仓库内 data/accounts/*.json 打入发行包（账号仅用户本机生成）
    accounts_dst = DATA_DIR / "accounts"
    accounts_dst.mkdir(parents=True, exist_ok=True)
    for stale in accounts_dst.glob("*.json"):
        try:
            stale.unlink()
        except OSError:
            pass
    print("[data] accounts/（空目录，不含 *.json）")

    # battle_character：运行态可编辑职业 .py，位于 Nuitka 外，可覆盖内置职业逻辑
    bc_src = PROJECT_ROOT / "data" / "battle_character"
    bc_dst = DATA_DIR / "battle_character"
    if bc_src.is_dir():
        shutil.copytree(
            bc_src,
            bc_dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        print("[data] battle_character/")
    else:
        bc_dst.mkdir(parents=True, exist_ok=True)
        print("[data] battle_character/ (空目录)")

    # assets/config (ui_map.csv 等)
    assets_config_src = PROJECT_ROOT / "ZmxyOL" / "assets" / "config"
    assets_dst = DATA_DIR / "assets" / "config"
    if assets_config_src.exists():
        shutil.copytree(assets_config_src, assets_dst, dirs_exist_ok=True)
        print("[data] assets/config/")

    # assets/pic (图片资源)
    assets_pic_src = PROJECT_ROOT / "ZmxyOL" / "assets" / "pic"
    pic_dst = DATA_DIR / "assets" / "pic"
    if assets_pic_src.exists():
        shutil.copytree(assets_pic_src, pic_dst, dirs_exist_ok=True)
        print("[data] assets/pic/")

    # license/ 目录 (占位)。electron-builder 不会稳定复制空目录，放一个小文件保证发布包结构可验证。
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    (LICENSE_DIR / "README.txt").write_text(
        "Reserved for release license notices and third-party attributions.\n",
        encoding="utf-8",
    )
    print("[data] license/ (README.txt)")

    # logs/ 目录 (占位)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)

    # custom_task/ 用户自定义 Python 任务（开发与发行均位于 data/custom_task）
    custom_src = PROJECT_ROOT / "data" / "custom_task"
    custom_dst = DATA_DIR / "custom_task"
    if custom_src.is_dir():
        shutil.copytree(
            custom_src,
            custom_dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        print("[data] custom_task/")
    else:
        custom_dst.mkdir(parents=True, exist_ok=True)
        print("[data] custom_task/ (空目录)")

    print("[data] 数据收集完成!")


def zip_backend_tree() -> None:
    """将 dist/gui.dist 打成 dist/backend.zip，供 Electron extraResources 随包携带；首次运行由向导解压到用户目录。"""
    if not NUITKA_OUT.is_dir():
        print(f"[zip] 错误: 缺少 Nuitka 目录 {NUITKA_OUT}，无法生成 backend.zip")
        sys.exit(1)
    copy_stdlib_encodings()
    copy_stdlib_wave()
    copy_stdlib_runtime_helpers()
    ensure_vc_runtime_dlls()
    ensure_python_stable_abi_dlls()
    zip_path = DIST_DIR / "backend.zip"
    if zip_path.exists():
        zip_path.unlink()
    print(f"[zip] 正在打包 {NUITKA_OUT} -> {zip_path} …")
    n_files = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(NUITKA_OUT):
            for name in files:
                fp = Path(root) / name
                arc = fp.relative_to(NUITKA_OUT)
                zf.write(fp, arc.as_posix())
                n_files += 1
    print(f"[zip] 完成，共 {n_files} 个文件 -> {zip_path}")


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _tail(text: str, max_lines: int = 80) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def validate_engine_runtime(timeout_s: int = 90) -> None:
    """Start the packaged engine and require the WebUI to answer on port 5000."""
    engine = NUITKA_OUT / ("autoscriptor-engine.exe" if os.name == "nt" else "autoscriptor-engine")
    if not engine.is_file():
        print(f"[smoke] 错误: 缺少 engine: {engine}")
        sys.exit(1)
    if _port_is_open("127.0.0.1", 5000):
        print("[smoke] 错误: 127.0.0.1:5000 已被占用，无法验证默认产品端口。")
        sys.exit(1)

    smoke_data = DIST_DIR / ".smoke-data"
    if smoke_data.exists():
        shutil.rmtree(smoke_data)
    shutil.copytree(DATA_DIR, smoke_data)

    env = os.environ.copy()
    env.update({
        "AUTOSCRIPTOR_ALLOW_MULTI_INSTANCE": "1",
        "AUTOSCRIPTOR_ELECTRON": "1",
        "AUTOSCRIPTOR_ELECTRON_PIPE": "1",
        "AUTOSCRIPTOR_DATA_DIR": str(smoke_data.resolve()),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "UVICORN_LOG_LEVEL": "info",
        "NO_COLOR": "1",
    })
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)

    import_report = smoke_data / "runtime-import-smoke.json"
    print("[smoke] packaged runtime import smoke...")
    import_smoke = subprocess.run(
        [
            str(engine),
            "--runtime-import-smoke",
            "--probe-out",
            str(import_report),
        ],
        cwd=str(NUITKA_OUT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=90,
    )
    if import_smoke.returncode != 0:
        print("[smoke] 错误: packaged runtime import smoke failed")
        if import_smoke.stdout:
            print("[smoke] stdout tail:\n" + _tail(import_smoke.stdout))
        if import_smoke.stderr:
            print("[smoke] stderr tail:\n" + _tail(import_smoke.stderr))
        print(f"[smoke] report: {import_report}")
        sys.exit(1)

    print(f"[smoke] 启动 engine: {engine}")
    proc = subprocess.Popen(
        [str(engine), "--electron"],
        cwd=str(NUITKA_OUT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    ready = False
    deadline = time.perf_counter() + timeout_s
    try:
        while time.perf_counter() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen("http://127.0.0.1:5000", timeout=2) as resp:
                    body = resp.read(4096).decode("utf-8", errors="replace")
                    if resp.status == 200 and ("AutoScriptor" in body or "造笔" in body):
                        ready = True
                        break
            except Exception:
                time.sleep(1)

        if ready:
            print("[smoke] WebUI 启动验证通过: http://127.0.0.1:5000")
            return

        if proc.poll() is None:
            _terminate_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        print(f"[smoke] 错误: engine 未在 {timeout_s}s 内启动成功，exit={proc.poll()}")
        if stdout:
            print("[smoke] stdout tail:\n" + _tail(stdout))
        if stderr:
            print("[smoke] stderr tail:\n" + _tail(stderr))
        sys.exit(1)
    finally:
        _terminate_process_tree(proc)
        shutil.rmtree(smoke_data, ignore_errors=True)


def build_electron(
    use_nsis: bool = False,
    timings: list[tuple[str, float]] | None = None,
    nsis_fast_install: bool = False,
    use_zip: bool = False,
):
    """运行 electron-builder 打包 Windows 桌面产物。

    先执行 webapp 内 prepare-release-shell（壳层混淆 + HTML 压缩），再在 .release-staging 下打包。

    默认：portable 单文件 exe（backend.zip、data 打入包内），首次运行即 installer.html 向导。
    use_nsis=True：生成 NSIS 系统安装程序（非 HTML 向导）。
    use_zip=True：生成 win-unpacked 的 zip 目录包（调试用）。
    nsis_fast_install：仅 NSIS，compression=store。
    """
    webapp_dir = PROJECT_ROOT / "webapp"
    staging = webapp_dir / ".release-staging"
    cfg = webapp_dir / "electron-builder.staging.config.js"
    print("[electron] 发布壳层准备 (混淆/压缩)...")
    t_prep = time.perf_counter()
    prep = subprocess.run(
        ["npm", "run", "prepare-release-shell"],
        cwd=str(webapp_dir),
        shell=True,
    )
    if timings is not None:
        timings.append(("Electron 壳层准备 (prepare-release-shell)", time.perf_counter() - t_prep))
    if prep.returncode != 0:
        print("[electron] 发布壳层准备失败!")
        sys.exit(1)
    if not staging.is_dir() or not (staging / "main.js").is_file():
        print(f"[electron] 缺少 staging 目录或 main.js: {staging}")
        sys.exit(1)
    if use_nsis:
        mode = "NSIS 系统安装包"
    elif use_zip:
        mode = "ZIP 文件夹包" 
    else:
        mode = "portable 单文件（AutoScriptor_Zao_Install_<version>.exe）"
    print(f"[electron] 开始打包 ({mode})...")
    env = os.environ.copy()
    if env.get("AUTOSCRIPTOR_CODE_SIGN") == "1":
        print("[electron] 已启用代码签名：将使用 electron-builder/CSC_* 环境变量或证书存储配置。")
    else:
        env.setdefault("CSC_IDENTITY_AUTO_DISCOVERY", "false")
    if use_nsis:
        env["AUTOSCRIPTOR_ELECTRON_NSIS"] = "1"
        if nsis_fast_install:
            env["AUTOSCRIPTOR_NSIS_FAST_INSTALL"] = "1"
            print("[electron] NSIS 使用 store 压缩（安装更快、安装包更大）")
        else:
            env.pop("AUTOSCRIPTOR_NSIS_FAST_INSTALL", None)
        env.pop("AUTOSCRIPTOR_ELECTRON_ZIP", None)
    else:
        env.pop("AUTOSCRIPTOR_ELECTRON_NSIS", None)
        env.pop("AUTOSCRIPTOR_NSIS_FAST_INSTALL", None)
        if use_zip:
            env["AUTOSCRIPTOR_ELECTRON_ZIP"] = "1"
        else:
            env.pop("AUTOSCRIPTOR_ELECTRON_ZIP", None)
    t_eb = time.perf_counter()
    result = subprocess.run(
        [
            "npx",
            "electron-builder",
            "--win",
            f"--config={cfg}",
        ],
        cwd=str(webapp_dir),
        shell=True,
        env=env,
    )
    if timings is not None:
        timings.append(("Electron 打包 (electron-builder)", time.perf_counter() - t_eb))
    if result.returncode != 0:
        print("[electron] 打包失败!")
        sys.exit(1)
    t_verify = time.perf_counter()
    verify = subprocess.run(
        ["npm", "run", "verify-pack"],
        cwd=str(webapp_dir),
        shell=True,
        env=env,
    )
    if timings is not None:
        timings.append(("Electron 打包自检 (verify-pack)", time.perf_counter() - t_verify))
    if verify.returncode != 0:
        print("[electron] 打包自检失败!")
        sys.exit(1)
    print("[electron] 打包完成!")
    if use_nsis:
        print(
            "[electron] 提示: NSIS 仅把壳与 data 放入安装目录；backend 仍在首次运行的 **HTML 安装向导** 中解压。"
        )
    elif use_zip:
        print(
            "[electron] 提示: 解压 dist_electron 内 ZIP 到任意文件夹，运行 造笔.exe；"
            "首次启动向导解压 backend 并配置 MuMu/ADB。"
        )
    else:
        print(
            "[electron] 提示: 分发 **AutoScriptor_Zao_Install_<version>.exe** 即可（单文件，已含 backend.zip；"
            "安装后安装目录会有 **造笔.exe** 启动器）；"
            "首次运行即打开安装向导（界面与便携流程一致），解压引擎后请在向导中确认 MuMu/ADB 路径。"
        )


def maybe_reexec_with_full_python() -> None:
    """若存在 .venv-nuitka（应用完整 Python 创建的 venv），则用其重新执行本脚本。

    嵌入式 Python 创建的 .venv 会导致 Nuitka standalone 运行时缺少 encodings；
    见 docs/AutoScriptor/release/nuitka-reference.md。构建前应执行:
      <NuGet 或 python.org 完整 Python> -m venv .venv-nuitka
      .venv-nuitka\\Scripts\\pip install -r requirements.txt nuitka ordered-set zstandard
    """
    preferred = PROJECT_ROOT / ".venv-nuitka" / "Scripts" / "python.exe"
    if not preferred.is_file():
        return
    try:
        if Path(sys.executable).resolve() == preferred.resolve():
            return
    except OSError:
        return
    script = Path(__file__).resolve()
    try:
        probe = subprocess.run(
            [str(preferred), "-c", "import sys; print(sys.executable)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[build] 警告: .venv-nuitka 不可执行，继续使用当前解释器: {e}")
        return
    if probe.returncode != 0:
        msg = (probe.stderr or probe.stdout or "").strip().splitlines()
        detail = msg[0] if msg else f"exit {probe.returncode}"
        print(f"[build] 警告: .venv-nuitka 不可执行，继续使用当前解释器: {detail}")
        return
    print(f"[build] 改用完整 Python 环境: {preferred}")
    result = subprocess.run([str(preferred), str(script)] + sys.argv[1:])
    sys.exit(result.returncode)


def main():
    maybe_reexec_with_full_python()

    parser = argparse.ArgumentParser(description="AutoScriptor 发行版构建")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="删除 dist/gui.build（冷编译，最慢；依赖/Nuitka 大升级或怀疑缓存损坏时用）",
    )
    parser.add_argument(
        "--skip-nuitka",
        action="store_true",
        help="跳过 Nuitka（沿用已有 dist/gui.dist；适合只改 webapp/Electron 壳时复用引擎）",
    )
    parser.add_argument(
        "--skip-electron",
        action="store_true",
        help="跳过 backend.zip 与 Electron（不装包；适合只验证/迭代 Python 引擎，省大量时间）",
    )
    parser.add_argument(
        "--skip-engine-smoke",
        action="store_true",
        help="跳过打包 engine 启动烟测（仅在端口被占用或本机环境专门调试时使用）",
    )
    parser.add_argument(
        "--incremental-backend-from",
        default="",
        metavar="PATH",
        help="指定上一版 gui.dist 目录或 backend.zip，额外生成 dist/backend_incremental.zip（文件级增量，体积小）",
    )
    parser.add_argument(
        "--incremental-from-label",
        default="",
        help="与 --incremental-backend-from 联用：写入清单的 from 标签（如 1.2.0）",
    )
    parser.add_argument(
        "--incremental-to-label",
        default="",
        help="与 --incremental-backend-from 联用：写入清单的 to 标签（如 1.2.1）",
    )
    parser.add_argument("--clean-only", action="store_true", help="仅清理构建产物")
    parser.add_argument(
        "--electron-nsis",
        action="store_true",
        help="桌面端生成 NSIS 系统安装程序（默认：portable 单 exe，无 NSIS）",
    )
    parser.add_argument(
        "--electron-zip",
        action="store_true",
        help="桌面端生成 win-unpacked 的 zip 目录包（调试用；默认 portable 单 exe）",
    )
    parser.add_argument(
        "--electron-nsis-fast-install",
        action="store_true",
        help="与 --electron-nsis 联用：NSIS 安装阶段更快（compression=store，安装包体积更大）",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="Nuitka C 编译并行任务数（内部传 --jobs=N，如 -j 16）；不传则使用 Nuitka 默认",
    )
    args = parser.parse_args()
    if args.electron_nsis_fast_install and not args.electron_nsis:
        print("[build] 错误: --electron-nsis-fast-install 需与 --electron-nsis 同时使用")
        sys.exit(2)
    if args.electron_nsis and args.electron_zip:
        print("[build] 警告: 同时指定 --electron-nsis 与 --electron-zip，将只生成 NSIS（忽略 zip）")
    if args.jobs is not None and args.jobs < 1:
        print("[build] 错误: -j/--jobs 须为 >= 1 的整数")
        sys.exit(2)
    if (args.incremental_from_label or args.incremental_to_label) and not args.incremental_backend_from:
        print("[build] 错误: --incremental-from-label / --incremental-to-label 需与 --incremental-backend-from 同时使用")
        sys.exit(2)

    print("=" * 60)
    print("  AutoScriptor 发行版构建")
    print("=" * 60)
    _print_incremental_cache_status(args)

    timings: list[tuple[str, float]] = []
    t_build = time.perf_counter()

    with timed_step(timings, "清理 (clean)"):
        clean(full=args.clean, skip_nuitka=args.skip_nuitka)

    if args.clean_only:
        _print_build_timings(timings, time.perf_counter() - t_build)
        return

    if not args.skip_nuitka:
        run_nuitka(timings=timings, jobs=args.jobs)
    else:
        print("[nuitka] 已跳过")
        post_process_nuitka_output(timings=timings)

    with timed_step(timings, "收集数据 (collect_data)"):
        collect_data()

    if not args.skip_engine_smoke:
        with timed_step(timings, "engine 启动烟测"):
            validate_engine_runtime()
    else:
        print("[smoke] 已跳过 engine 启动烟测")

    if not args.skip_electron:
        with timed_step(timings, "打包 backend.zip"):
            zip_backend_tree()
    elif args.incremental_backend_from:
        if not NUITKA_OUT.is_dir():
            print(f"[build] 错误: 缺少 {NUITKA_OUT}，无法生成增量包（勿与 --skip-nuitka 且无现成 gui.dist 联用）")
            sys.exit(2)

    if args.incremental_backend_from:
        inc_path = Path(args.incremental_backend_from).resolve()
        if not inc_path.exists():
            print(f"[build] 错误: --incremental-backend-from 不存在: {inc_path}")
            sys.exit(2)
        if not NUITKA_OUT.is_dir():
            print(f"[build] 错误: 缺少 {NUITKA_OUT}，无法生成增量包")
            sys.exit(2)
        inc_out = DIST_DIR / "backend_incremental.zip"
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "release" / "release_backend_incremental.py"),
            "create",
            "--old",
            str(inc_path),
            "--new",
            str(NUITKA_OUT),
            "--out",
            str(inc_out),
        ]
        if args.incremental_from_label:
            cmd += ["--from-label", args.incremental_from_label]
        if args.incremental_to_label:
            cmd += ["--to-label", args.incremental_to_label]
        with timed_step(timings, "打包 backend_incremental.zip"):
            r = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if r.returncode != 0:
            print("[build] incremental 包生成失败")
            sys.exit(1)

    if not args.skip_electron:
        build_electron(
            use_nsis=args.electron_nsis,
            timings=timings,
            nsis_fast_install=args.electron_nsis_fast_install,
            use_zip=args.electron_zip and not args.electron_nsis,
        )
    else:
        print("[electron] 已跳过")

    print()
    print("=" * 60)
    print("  构建完成!")
    print(f"  Nuitka 产物: {NUITKA_OUT}")
    print(f"  数据文件:    {DATA_DIR}")
    if not args.skip_electron:
        if args.electron_nsis:
            kind = "NSIS 安装程序"
        elif args.electron_zip:
            kind = "ZIP 文件夹包"
        else:
            kind = "portable 单文件（AutoScriptor_Zao_Install_<version>.exe + 安装目录 造笔.exe）"
        print(f"  桌面产物 ({kind}):  {DIST_ELECTRON_DIR} (electron-builder，与 dist/ 互不覆盖)")
    if args.incremental_backend_from:
        print(f"  增量包:      {DIST_DIR / 'backend_incremental.zip'}（已安装用户可单独分发此文件升级引擎）")
    print("=" * 60)
    _print_build_timings(timings, time.perf_counter() - t_build)


if __name__ == "__main__":
    main()
