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
from pathlib import Path


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


def _count_requirements(req_path: Path) -> int:
    n = 0
    for line in req_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("-"):
            n += 1
    return n


def run_install(project_root: Path, pip_source: str | None = None) -> int:
    total = 4

    # ── Step 1: Python ──────────────────────────────────────────────
    _step("python", "检查 Python 环境", "running", 0, total)
    _progress(5, "检查 Python 版本...")
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    _log(f"Python {ver} — {sys.executable}")
    if sys.version_info < (3, 10):
        _error(f"需要 Python 3.10+，当前版本 {ver}")
        return 1
    _step("python", "检查 Python 环境", "done", 0, total)
    _progress(10, "Python 环境就绪")

    # ── Step 2: Venv ────────────────────────────────────────────────
    venv_dir = project_root / ".venv"
    venv_py = venv_dir / "Scripts" / "python.exe"

    _step("venv", "创建虚拟环境", "running", 1, total)
    if venv_py.exists():
        _log("虚拟环境已存在，跳过创建")
    else:
        _progress(12, "正在创建虚拟环境...")
        _log(f"目标: {venv_dir}")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "venv", str(venv_dir)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            _log("虚拟环境创建成功")
        except subprocess.CalledProcessError as e:
            _error(f"创建虚拟环境失败 (exit {e.returncode})")
            return 1
    _step("venv", "创建虚拟环境", "done", 1, total)
    _progress(18, "虚拟环境就绪")

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
            subprocess.check_call(
                [str(venv_py), "-m", "pip", "install", "--upgrade",
                 "pip", "setuptools<82", "wheel"],
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

        cmd = [str(venv_py), "-m", "pip", "install",
               "-r", str(req_path), "--progress-bar", "off"]
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
            subprocess.check_call(
                [str(venv_py), "-m", "pip", "install",
                 "--upgrade", "--force-reinstall", "setuptools<82"],
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
    args = parser.parse_args()
    return run_install(Path(args.project_root).resolve(), args.pip_source)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        _error(f"安装异常: {exc}")
        sys.exit(1)
