#!/usr/bin/env python3
"""
打包前自检（数秒级，不跑 Nuitka）
================================
在跑 `build_release.py`（往往 20+ 分钟）之前，用**同一套**将用于编译的 Python 验证：

- 关键 pip 包能否 import（含 multipart，避免白等一轮）
- 仓库内是否已包含 Nuitka 对 multipart / python_multipart 的 include-module 配置、server 显式 import

用法（与打包容器一致）::

    .\\.venv-nuitka\\Scripts\\python.exe scripts\\verify_packaging_prereqs.py

若通过再执行::

    .\\.venv-nuitka\\Scripts\\python.exe scripts\\build_release.py

退出码：0 通过，1 失败。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 与 WebUI / 发行引擎启动强相关；缺任一则运行时易炸
_IMPORT_LINE = """
import multipart
import python_multipart
import fastapi
import starlette
import pydantic
import uvicorn
import websockets
import dpath
print("imports_ok")
"""


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _load_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"{path.relative_to(PROJECT_ROOT)} is not valid JSON: {e}"
    if not isinstance(data, dict):
        return None, f"{path.relative_to(PROJECT_ROOT)} must be a JSON object"
    return data, None


def _check_config_template() -> list[str]:
    errors: list[str] = []
    tpl = PROJECT_ROOT / "config template.json"
    if not tpl.is_file():
        return ["missing config template.json"]
    cfg, err = _load_json(tpl)
    if err:
        return [err]
    assert cfg is not None
    for key in ("app", "emulator", "ocr", "deploy", "accounts", "current_account"):
        if key not in cfg:
            errors.append(f"config template.json missing required section: {key}")
    if (cfg.get("app") or {}).get("name") != "ZmxyOL":
        errors.append("config template.json app.name must be ZmxyOL")
    accounts_dir = str((cfg.get("accounts") or {}).get("dir") or "").strip()
    if accounts_dir and Path(accounts_dir).is_absolute():
        errors.append("config template.json accounts.dir must not be an absolute path")
    return errors


def _compile_tree(root: Path) -> list[str]:
    errors: list[str] = []
    if not root.exists():
        return errors
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            compile(py.read_text(encoding="utf-8"), str(py), "exec")
        except SyntaxError as e:
            errors.append(f"Python compile failed: {py.relative_to(PROJECT_ROOT)}: {e}")
    return errors


def _check_runtime_data_tree() -> list[str]:
    errors: list[str] = []
    ui_map = PROJECT_ROOT / "ZmxyOL" / "assets" / "config" / "ui_map.csv"
    if not ui_map.is_file():
        errors.append("missing ZmxyOL/assets/config/ui_map.csv")
    else:
        lines = ui_map.read_text(encoding="utf-8", errors="replace").splitlines()
        header = lines[0].split(",") if lines else []
        for col in ("key", "text", "left", "top", "width", "height", "img"):
            if col not in header:
                errors.append(f"ui_map.csv missing column: {col}")

    hero = PROJECT_ROOT / "data" / "battle_character" / "hero.py"
    if not hero.is_file():
        errors.append("missing data/battle_character/hero.py")

    errors.extend(_compile_tree(PROJECT_ROOT / "data" / "battle_character"))
    errors.extend(_compile_tree(PROJECT_ROOT / "data" / "custom_task"))
    return errors


def _check_generated_code_templates() -> list[str]:
    snippets = [
        'from AutoScriptor import *\nclick(B(10, 20, 30, 40), timeout=3)',
        'from AutoScriptor import *\nclick(T("确定", box=Box(10, 20, 30, 40).margin()), timeout=3)',
        'from AutoScriptor import *\nclick(I("确定", box=Box(10, 20, 30, 40).margin()), timeout=3)',
        'from AutoScriptor import *\nswipe(B(10,20,1,1), B(10,80,1,1), duration_s=1)',
        'from AutoScriptor import *\ninfo = extract_info(B(10,20,30,40), post_process=lambda s: s.strip(), ensure_not_empty=True)',
        'from AutoScriptor import *\ncounts = extract_info(make_box_grid(Box(10,20,30,40), Box(10,20,30,40), row=1, col=1), digital=True)',
    ]
    errors: list[str] = []
    for idx, code in enumerate(snippets, 1):
        try:
            compile(code, f"<generated-template-{idx}>", "exec")
        except SyntaxError as e:
            errors.append(f"generated code template {idx} does not compile: {e}")
    return errors


def _check_repo_files() -> list[str]:
    errors: list[str] = []
    br = PROJECT_ROOT / "scripts" / "build_release.py"
    text = _read_text(br)
    if "--include-module=multipart" not in text:
        errors.append(f"缺少 Nuitka 参数: --include-module=multipart（{br.name}）")
    if "--include-module=python_multipart" not in text:
        errors.append(f"缺少 Nuitka 参数: --include-module=python_multipart（{br.name}）")
    sv = PROJECT_ROOT / "services" / "webui" / "server.py"
    st = _read_text(sv)
    if "\nimport multipart" not in st and not st.startswith("import multipart"):
        errors.append(f"缺少显式 import multipart（{sv.relative_to(PROJECT_ROOT)}）")
    errors.extend(_check_config_template())
    errors.extend(_check_runtime_data_tree())
    errors.extend(_check_generated_code_templates())
    return errors


def _run_py(py: str, code: str) -> tuple[int, str]:
    r = subprocess.run(
        [py, "-c", code],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Nuitka 打包前快速自检")
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="用于发版/Nuitka 的解释器（默认当前解释器）",
    )
    args = ap.parse_args()
    py = str(Path(args.python).resolve())

    print(f"[verify] 使用解释器: {py}")
    print("[verify] 检查仓库配置（multipart 纳入 Nuitka + server import）…")
    file_errs = _check_repo_files()
    if file_errs:
        for e in file_errs:
            print(f"  FAIL: {e}")
        return 1
    print("  OK")

    print("[verify] 检查解释器版本…")
    code, out = _run_py(py, "import sys; print(sys.version_info[:2]); print(sys.base_prefix)")
    if code != 0:
        print(f"  FAIL: 无法执行 {py}\n{out}")
        return 1
    lines = out.splitlines()
    try:
        ver = eval(lines[0])  # (3, 10)
        if ver < (3, 10):
            print(f"  WARN: 建议使用 Python 3.10+，当前为 {ver}")
        else:
            print(f"  OK: Python {ver[0]}.{ver[1]}")
    except Exception:
        print(f"  WARN: 无法解析版本: {out}")

    bp = lines[-1] if lines else ""
    if sys.platform == "win32" and bp.lower().endswith("scripts"):
        print(
            "  WARN: base_prefix 指向 Scripts，疑似嵌入式 Python venv；"
            "若 Nuitka 产物缺 encodings，请改为完整 Python 安装版，见 docs/AutoScriptor/nuitka-reference.md"
        )

    print("[verify] 批量 import 关键依赖（multipart / fastapi / …）…")
    code, out = _run_py(py, _IMPORT_LINE)
    if code != 0 or "imports_ok" not in out:
        print(f"  FAIL: 依赖未装全或版本不兼容。\n{out}")
        print("  请在该 venv 中执行: pip install -r requirements.txt")
        return 1
    print("  OK")

    print("[verify] 全部通过。可再运行: python scripts/build_release.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
