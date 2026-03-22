"""
Electron 图形安装器的后端安装步骤脚本。

用法:
    python install_steps.py --project-root DIR [--pip-source URL]

每行 stdout 输出一个 JSON 对象，供 Electron 主进程 IPC 转发给渲染进程:
    {"type":"step",     "id":str, "title":str, "status":"running"|"done", "index":int, "total":int}
    {"type":"progress", "percent":int, "message":str}
    {"type":"log",      "message":str}
    {"type":"error",    "message":str}
    {"type":"complete"}
"""

import sys
import os
import json
import subprocess
import argparse
import urllib.request
from pathlib import Path

REQUIRED_PYTHON = (3, 10)
BOOTSTRAP_PY_VERSION = "3.10.11"
BOOTSTRAP_PY_DIR_NAME = ".python310"


def _emit(data: dict):
    # ensure_ascii=True 避免 JSON 中出现原始中文字符，
    # 防止 Electron 管道的 GBK 回退启发式把 UTF-8 中文误判为 GBK 导致乱码
    sys.stdout.write(json.dumps(data, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _log(msg: str):
    _emit({"type": "log", "message": msg})


def _progress(pct: int, msg: str = ""):
    _emit({"type": "progress", "percent": min(pct, 100), "message": msg})


def _step(sid: str, title: str, status: str, idx: int = 0, total: int = 4):
    _emit({"type": "step", "id": sid, "title": title, "status": status,
           "index": idx, "total": total})


def _error(msg: str):
    _emit({"type": "error", "message": msg})


def _complete():
    _emit({"type": "complete"})


def _detect_security_software() -> list[str]:
    """Detect running security software that may slow down venv file operations."""
    known = {
        "360tray.exe": "360\u5b89\u5168\u536b\u58eb",
        "360safe.exe": "360\u5b89\u5168\u536b\u58eb",
        "360sd.exe": "360\u6740\u6bd2",
        "zhudongfangyu.exe": "360\u4e3b\u52a8\u9632\u5fa1",
        "hipstray.exe": "\u706b\u7ed2\u5b89\u5168",
        "wsctrlsvc.exe": "\u706b\u7ed2\u5b89\u5168",
        "qqpctray.exe": "\u817e\u8baf\u7535\u8111\u7ba1\u5bb6",
        "kxetray.exe": "\u91d1\u5c71\u6bd2\u9738",
        "avp.exe": "\u5361\u5df4\u65af\u57fa",
    }
    found: list[str] = []
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        for line in out.stdout.splitlines():
            if not line.strip():
                continue
            name = line.split(",")[0].strip('"').lower()
            if name in known and known[name] not in found:
                found.append(known[name])
    except Exception:
        pass
    return found


def _try_add_defender_exclusion(target_path: str) -> bool:
    """Best-effort: add Windows Defender real-time scan exclusion for *target_path*."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Add-MpPreference -ExclusionPath "{target_path}" -ErrorAction SilentlyContinue'],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def _env_fresh_install() -> bool:
    v = os.environ.get("AUTOSCRIPTOR_FRESH_INSTALL", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _apply_fresh_install_prep(project_root: Path) -> None:
    """清除依赖标记与 wheelhouse 内 Python 安装包缓存。"""
    stamp = project_root / ".venv" / ".deps_installed.stamp"
    stamp.unlink(missing_ok=True)
    py_cache = project_root / "wheelhouse" / "python"
    if py_cache.is_dir():
        for p in py_cache.glob("*.exe"):
            try:
                p.unlink()
            except OSError:
                pass


def _pip_cache_purge(venv_python: Path) -> None:
    try:
        subprocess.run(
            [str(venv_python), "-m", "pip", "cache", "purge"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception:
        pass


def _count_requirements(req_path: Path) -> int:
    n = 0
    for line in req_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("-"):
            n += 1
    return n


def _bootstrap_python(project_root: Path, fresh: bool = False) -> Path:
    """Download and install Python 3.10 into project-local directory. Returns python.exe path."""
    py_dir = project_root / BOOTSTRAP_PY_DIR_NAME
    py_exe = py_dir / "python.exe"
    if py_exe.exists():
        _log(f"已存在本地 Python: {py_exe}")
        return py_exe

    cache_dir = project_root / "wheelhouse" / "python"
    cache_dir.mkdir(parents=True, exist_ok=True)

    installer_name = f"python-{BOOTSTRAP_PY_VERSION}-amd64.exe"
    url = os.environ.get(
        "AUTOSCRIPTOR_PYTHON_URL",
        f"https://www.python.org/ftp/python/{BOOTSTRAP_PY_VERSION}/{installer_name}",
    )
    installer_path = cache_dir / installer_name

    if fresh and installer_path.exists():
        installer_path.unlink(missing_ok=True)
        _log("已清除 Python 安装包缓存，将重新下载")

    if not installer_path.exists():
        _log(f"下载 Python {BOOTSTRAP_PY_VERSION}...")
        _progress(6, f"下载 Python {BOOTSTRAP_PY_VERSION}...")
        urllib.request.urlretrieve(url, str(installer_path))
        _log("下载完成")

    py_dir.mkdir(parents=True, exist_ok=True)
    _log(f"安装 Python {BOOTSTRAP_PY_VERSION} 到 {py_dir}...")
    _progress(7, f"安装 Python {BOOTSTRAP_PY_VERSION}...")

    args = [
        str(installer_path), "/quiet",
        "SimpleInstall=1", "InstallAllUsers=0",
        "Include_pip=1", "Include_launcher=0",
        "PrependPath=0", "Shortcuts=0", "Include_test=0",
        f"TargetDir={py_dir}",
    ]
    ret = subprocess.call(args)
    if ret not in (0, 3010):
        _log(f"安装退出码: {ret}，尝试重新下载...")
        installer_path.unlink(missing_ok=True)
        urllib.request.urlretrieve(url, str(installer_path))
        ret = subprocess.call(args)
        if ret not in (0, 3010):
            raise RuntimeError(f"Python {BOOTSTRAP_PY_VERSION} 安装失败 (exit {ret})")

    if not py_exe.exists():
        raise FileNotFoundError(f"安装后未找到 {py_exe}")

    _log(f"Python {BOOTSTRAP_PY_VERSION} 安装成功")
    return py_exe


def _resolve_python(project_root: Path, fresh: bool = False) -> str:
    """Return a Python 3.10.x executable path. Bootstrap-install if needed."""
    # 精确匹配 3.10.x — 不接受更高的 minor 版本
    if sys.version_info[:2] == REQUIRED_PYTHON:
        return sys.executable

    local_py = project_root / BOOTSTRAP_PY_DIR_NAME / "python.exe"
    if local_py.exists():
        return str(local_py)

    return str(_bootstrap_python(project_root, fresh=fresh))


def run_install(project_root: Path, pip_source: str | None = None, fresh: bool = False) -> int:
    total = 4

    if fresh:
        _apply_fresh_install_prep(project_root)
        _log("全新安装：已清除依赖标记、pip 将不使用本地 wheel 缓存目录")

    # ── Step 1: Python ──────────────────────────────────────────────
    py_req = f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}"
    _step("python", f"检查 Python 环境 (python=={py_req})", "running", 0, total)
    _progress(5, "检查 Python 版本...")
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    _log(f"当前 Python {ver} — {sys.executable}")

    if sys.version_info[:2] != REQUIRED_PYTHON:
        _log(f"当前 Python {ver} 不是 {py_req}.x，将引导安装 Python {BOOTSTRAP_PY_VERSION}")

    try:
        target_python = _resolve_python(project_root, fresh=fresh)
    except Exception as exc:
        _error(f"Python {BOOTSTRAP_PY_VERSION} 安装失败: {exc}")
        return 1

    target_ver = ver
    if target_python != sys.executable:
        target_ver = subprocess.check_output(
            [target_python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"],
            text=True,
        ).strip()
        _log(f"使用 Python {target_ver} — {target_python}")

    _step("python", f"检查 Python 环境 (python=={py_req}, 当前 {target_ver})", "done", 0, total)
    _progress(10, f"Python {target_ver} 环境就绪")

    # ── Step 2: Venv ────────────────────────────────────────────────
    venv_dir = project_root / ".venv"
    venv_py = venv_dir / "Scripts" / "python.exe"

    _step("venv", f"创建虚拟环境 (.venv)", "running", 1, total)
    if venv_py.exists():
        _log(f"虚拟环境已存在，跳过创建: {venv_dir}")
    else:
        _progress(12, "正在创建虚拟环境 (.venv)...")
        _log(f"目标: {venv_dir}")
        try:
            subprocess.check_call(
                [target_python, "-m", "venv", str(venv_dir)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            _log("虚拟环境创建成功")
        except subprocess.CalledProcessError as e:
            _error(f"创建虚拟环境失败 (exit {e.returncode})")
            return 1
    _step("venv", f"创建虚拟环境 (.venv)", "done", 1, total)
    _progress(18, "虚拟环境就绪")

    if fresh:
        _pip_cache_purge(venv_py)

    # ── Antivirus check ────────────────────────────────────────────
    av_list = _detect_security_software()
    _try_add_defender_exclusion(str(venv_dir))
    _try_add_defender_exclusion(str(project_root))
    if av_list:
        names = "\u3001".join(av_list)
        _log(f"\u68c0\u6d4b\u5230\u5b89\u5168\u8f6f\u4ef6: {names}")
        _emit({
            "type": "warning",
            "message": f"\u68c0\u6d4b\u5230 {names} \u6b63\u5728\u8fd0\u884c\uff0c\u5176\u5b9e\u65f6\u626b\u63cf\u53ef\u80fd\u663e\u8457\u62d6\u6162\u5b89\u88c5\u548c\u8fd0\u884c\u901f\u5ea6\u3002",
            "detail": f"\u5efa\u8bae\u5c06\u4ee5\u4e0b\u76ee\u5f55\u6dfb\u52a0\u5230\u5b89\u5168\u8f6f\u4ef6\u7684\u767d\u540d\u5355/\u4fe1\u4efb\u533a:\n{project_root}",
        })

    # ── Step 3: Dependencies ────────────────────────────────────────
    _step("deps", "安装依赖", "running", 2, total)
    stamp = venv_dir / ".deps_installed.stamp"
    if stamp.exists():
        _log("依赖已安装（标记文件存在），跳过")
        _step("deps", "安装依赖", "done", 2, total)
        _progress(88)
    else:
        _progress(20, "升级 pip...")
        _log("pip install --upgrade pip setuptools wheel")
        try:
            if fresh:
                up_cmd = [str(venv_py), "-m", "pip", "install", "--no-cache-dir", "--upgrade",
                          "pip", "setuptools<82", "wheel"]
            else:
                up_cmd = [str(venv_py), "-m", "pip", "install", "--upgrade",
                          "pip", "setuptools<82", "wheel"]
            subprocess.check_call(
                up_cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError:
            _log("pip 升级跳过")

        req_path = project_root / "requirements.txt"
        if not req_path.exists():
            _error(f"找不到 {req_path}")
            return 1

        direct_pkgs = _count_requirements(req_path)
        # pip 会安装大量子依赖，实际包数通常是直接依赖的 3-5 倍
        estimated_total = direct_pkgs * 4
        _log(f"共 {direct_pkgs} 个直接依赖（预估 ~{estimated_total} 个包含子依赖）")
        _progress(22, f"安装依赖 (0/{direct_pkgs})...")

        cmd = [str(venv_py), "-m", "pip", "install", "--progress-bar", "off"]
        if fresh:
            cmd += ["--no-cache-dir", "--upgrade", "--force-reinstall"]
        cmd += ["-r", str(req_path)]
        if pip_source:
            cmd += ["-i", pip_source]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        collected = 0
        downloading = False
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            _log(line)
            if line.startswith("Collecting ") or line.startswith("Requirement already satisfied"):
                collected += 1
                pct = 22 + int(46 * min(collected / max(estimated_total, 1), 1.0))
                _progress(pct, f"解析依赖 ({collected})...")
            elif line.startswith("Downloading ") or line.startswith("Using cached "):
                if not downloading:
                    downloading = True
                    _progress(70, "下载依赖包...")
            elif line.startswith("Installing collected packages"):
                _progress(82, "安装中...")
            elif "Successfully installed" in line:
                _progress(85, "依赖安装完成")

        proc.wait()
        if proc.returncode != 0:
            _error(f"pip install 失败 (exit {proc.returncode})")
            return 1

        # setuptools >= 82 移除了 pkg_resources，adbutils 等库仍依赖它
        _progress(86, "修复 setuptools...")
        _log("pip install --upgrade --force-reinstall 'setuptools<82'")
        try:
            if fresh:
                fix_cmd = [str(venv_py), "-m", "pip", "install", "--no-cache-dir",
                           "--upgrade", "--force-reinstall", "setuptools<82"]
            else:
                fix_cmd = [str(venv_py), "-m", "pip", "install",
                           "--upgrade", "--force-reinstall", "setuptools<82"]
            subprocess.check_call(
                fix_cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            _log("setuptools 修复完成")
        except subprocess.CalledProcessError:
            _log("setuptools 修复跳过（非致命）")

        _progress(88)

        try:
            stamp.write_text("ok", encoding="utf-8")
        except Exception:
            pass
        _step("deps", "安装依赖", "done", 2, total)

    # ── Step 4: Configure ───────────────────────────────────────────
    _step("config", "环境配置", "running", 3, total)
    _progress(90, "检测 MuMu 模拟器...")

    try:
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from services.installer.installer import ensure_config_with_mumu
        ensure_config_with_mumu(project_root)
        _log("MuMu 模拟器路径已自动配置")
    except Exception as exc:
        _log(f"MuMu 自动检测跳过: {exc}")

    _progress(98, "写入配置...")
    _step("config", "环境配置", "done", 3, total)
    _progress(100, "安装完成！")
    _complete()
    return 0


def main():
    parser = argparse.ArgumentParser(description="AutoScriptor Install Steps")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--pip-source", default=None)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="清除 pip 缓存与本地标记，强制从索引重新下载并重装依赖（也可用环境变量 AUTOSCRIPTOR_FRESH_INSTALL=1）",
    )
    args = parser.parse_args()
    fresh = bool(args.fresh) or _env_fresh_install()
    return run_install(Path(args.project_root).resolve(), args.pip_source, fresh=fresh)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        _error(f"安装异常: {exc}")
        sys.exit(1)
