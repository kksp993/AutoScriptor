import sys
import os
import subprocess
from pathlib import Path
import json
import questionary
from typing import Any

# 运行环境下既支持包内相对导入，也尽量兼容以脚本方式直接运行
try:
    from .git_service import GitService  # type: ignore
    from .env_config import EnvConfig  # type: ignore
except Exception:
    try:
        from AutoScriptor.installer.git_service import GitService  # type: ignore
        from AutoScriptor.installer.env_config import EnvConfig  # type: ignore
    except Exception:
        GitService = None  # type: ignore
        EnvConfig = None  # type: ignore

try:
    import winreg  # type: ignore
except Exception:
    winreg = None  # 非 Windows 环境兼容

COMMON_MUMU_PORTS =[
    16384,16416,16448,16480,16512,16544,16576,16608
]


def find_project_root(start: Path) -> Path:
    """Locate project root by looking for requirements.txt at or above start."""
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / "requirements.txt").exists() and (p / "services").exists():
            return p
    # Fallback: two levels up from this file (AutoScriptor/installer → repo root)
    return start.resolve().parents[2]


def get_venv_python(project_root: Path) -> Path:
    return project_root / ".venv" / "Scripts" / "python.exe"


def ensure_venv(project_root: Path) -> Path:
    """Create .venv if missing. Returns venv python path."""
    venv_python = get_venv_python(project_root)
    if venv_python.exists():
        return venv_python
    # Create venv using the current interpreter
    subprocess.check_call([sys.executable, "-m", "venv", str(project_root / ".venv")])
    return venv_python


def reinstall_pip_and_install(project_root: Path, extra_index: str | None = None) -> None:
    venv_python = get_venv_python(project_root)
    # Upgrade pip first (use python -m pip to avoid self-modify issues)
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]) 
    # 标准在线安装；不再优先 wheelhouse
    req = project_root / "requirements.txt"
    args = [str(venv_python), "-m", "pip", "install", "-r", str(req)]
    if extra_index:
        args += ["-i", extra_index]
    subprocess.check_call(args)


def _read_registry_mu_mu_paths() -> list[Path]:
    paths: list[Path] = []
    if winreg is None:
        return paths
    uninstall_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    keywords = ["MuMu", "MuMu Player", "网易 MuMu"]
    for root, sub in uninstall_roots:
        try:
            with winreg.OpenKey(root, sub) as h:  # type: ignore[attr-defined]
                for i in range(0, 4096):
                    try:
                        name = winreg.EnumKey(h, i)
                        with winreg.OpenKey(h, name) as appkey:
                            display_name = ""
                            install_loc = ""
                            try:
                                display_name, _ = winreg.QueryValueEx(appkey, "DisplayName")
                            except Exception:
                                pass
                            try:
                                install_loc, _ = winreg.QueryValueEx(appkey, "InstallLocation")
                            except Exception:
                                pass
                            text = f"{display_name} {install_loc}".lower()
                            if any(k.lower() in text for k in keywords):
                                if install_loc and os.path.isdir(install_loc):
                                    paths.append(Path(install_loc))
                    except OSError:
                        break
        except Exception:
            continue
    return paths


def _search_common_mu_mu_paths() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    pf = os.environ.get("ProgramFiles", r"C:\\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)")

    # 预置常见的安装目录名称（相对路径）
    common_names = [
        "Netease\\MuMu",
        "Netease\\MuMu Player 12",
        "MuMu",
        "MuMu Player 12",
    ]

    # 构建所有需要检查的基目录：
    # - 当前环境变量中的 Program Files 目录（通常是 C 盘）
    # - 所有存在的盘符根目录，以及对应盘符下的 Program Files 与 Program Files (x86)
    base_dirs: list[Path] = [Path(pf), Path(pf86)]

    for code in range(ord('A'), ord('Z') + 1):
        root = f"{chr(code)}:\\"
        if os.path.exists(root):
            root_path = Path(root)
            base_dirs.append(root_path)
            base_dirs.append(root_path / "Program Files")
            base_dirs.append(root_path / "Program Files (x86)")

    # 遍历基目录与常见相对路径组合，收集合规存在的候选路径
    for base_dir in base_dirs:
        for name in common_names:
            path = base_dir / name
            try:
                if path.exists():
                    norm_key = os.path.normcase(os.path.normpath(str(path)))
                    if norm_key not in seen:
                        candidates.append(path)
                        seen.add(norm_key)
            except Exception:
                # 某些路径在个别环境下可能触发异常，忽略继续
                continue

    return candidates


def _derive_paths_from_mumu_folder(folder: Path) -> dict:
    # 兼容老版（nx_main）与 12 版（shell）
    nx_main = folder / "nx_main"
    shell = folder / "shell"
    emu_path = None
    adb_path = None
    if nx_main.exists():
        ep = nx_main / "MuMuManager.exe"
        ap = nx_main / "adb.exe"
        if ep.exists():
            emu_path = ep
        if ap.exists():
            adb_path = ap
    if (emu_path is None or adb_path is None) and shell.exists():
        ep = shell / "MuMuPlayer.exe"
        ap = shell / "adb.exe"
        if emu_path is None and ep.exists():
            emu_path = ep
        if adb_path is None and ap.exists():
            adb_path = ap
    return {
        "mumu_folder": str(folder),
        "emu_path": str(emu_path) if emu_path else "",
        "adb_path": str(adb_path) if adb_path else "",
    }


def _adb_detect_serial(adb_path: str) -> str | None:
    try:
        # 启动 ADB 服务并读取设备
        subprocess.run([adb_path, "start-server"], capture_output=True, text=True, timeout=5)
        out = subprocess.run([adb_path, "devices"], capture_output=True, text=True, timeout=5)
        lines = (out.stdout or "").splitlines()
        # 过滤 header 行
        pairs = [ln.split("\t")[0] for ln in lines if "\tdevice" in ln]
        for serial in pairs:
            if serial.startswith("127.0.0.1:"):
                return serial
        return pairs[0] if pairs else None
    except Exception:
        return None


def ensure_config_with_mumu(project_root: Path) -> None:
    """确保存在 config.json，并尽量自动填写 MuMu 相关字段。"""
    cfg_tmpl = project_root / "config template.json"
    cfg_path = project_root / "config.json"
    if not cfg_path.exists():
        if cfg_tmpl.exists():
            cfg_path.write_text(cfg_tmpl.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            # 最小结构
            cfg_path.write_text(json.dumps({
                "app": {"name": "ZmxyOL", "app_to_start": "org.yjmobile.zmxy", "restart_on_error": True, "run_in_background": True, "auto_start": True},
                "emulator": {"index": 1, "adb_addr": "127.0.0.1:16416", "max_retry": 3,"mumu_folder": "", "emu_path": "", "adb_path": ""},
                "encryption": {},
                "ocr": {"use_gpu": False},
                "tasks": {}
            }, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return

    emulator = data.setdefault("emulator", {})

    # 若缺省或占位符，则尝试自动探测
    need_detect = False
    for key in ("mumu_folder", "emu_path", "adb_path"):
        val = str(emulator.get(key, ""))
        if not val or val.startswith("YOUR_"):
            need_detect = True
            break

    if need_detect:
        candidates = []
        candidates.extend(_read_registry_mu_mu_paths())
        candidates.extend(_search_common_mu_mu_paths())
        chosen = None
        # 排除 Global 版
        for c in candidates:
            if "global" in str(c).lower():
                continue
            chosen = c
            break
        if chosen is not None:
            paths = _derive_paths_from_mumu_folder(chosen)
            for k, v in paths.items():
                if v and (not emulator.get(k) or str(emulator.get(k, "")).startswith("YOUR_")):
                    emulator[k] = v

    # 自动检测 adb 设备地址
    adb_addr = str(emulator.get("adb_addr", ""))
    if (not adb_addr or adb_addr.startswith("YOUR_") or adb_addr.endswith(":0")) and emulator.get("adb_path"):
        serial = _adb_detect_serial(emulator["adb_path"]) or ""
        if serial:
            emulator["adb_addr"] = serial
        else:
            index = questionary.text("Please enter the Mumu index:").ask()
            if index in COMMON_MUMU_PORTS:
                emulator["index"] = int(index)
                emulator["adb_addr"] = f"127.0.0.1:{index}"
            else:
                emulator["index"] = 0
                emulator["adb_addr"] = "127.0.0.1:16384"

    # 回写
    try:
        cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def relaunch_in_venv_if_needed(project_root: Path, argv: list[str]) -> None:
    """If not running inside the target .venv, relaunch inside it."""
    venv_python = get_venv_python(project_root)
    # Heuristic: compare current executable path to venv path
    if Path(sys.executable).resolve() != venv_python.resolve():
        if not venv_python.exists():
            ensure_venv(project_root)
        # Relaunch inside venv
        os.execv(str(venv_python), [str(venv_python), *argv])


def run_target(project_root: Path, target: str) -> int:
    venv_python = get_venv_python(project_root)
    if target == "webui":
        module = "services.webui.server"
    elif target == "cli":
        module = "services.main_cli.run"
    elif target == "install-only":
        return 0
    else:
        print(f"未知目标: {target}，可选: webui | cli | install-only")
        return 2
    # 使用模块方式并将 cwd 设为项目根，确保包可被正确导入
    return subprocess.call([str(venv_python), "-m", module], cwd=str(project_root))


def main() -> int:
    # Resolve project root from this file location
    this_file = Path(__file__).resolve()
    project_root = find_project_root(this_file.parent)

    # First phase: if not already in the target .venv, relaunch into it
    # (This also creates venv when missing.)
    relaunch_in_venv_if_needed(project_root, sys.argv)

    # 安全更新：将本地 deploy 分支同步到 origin/main，并在运行结束后恢复原始分支与工作区状态
    git_state: dict[str, Any] = {}
    git_helper = None
    try:
        if GitService is not None and EnvConfig is not None:
            git_helper = GitService(EnvConfig(), None, None)
            # 若系统没有 git，则跳过安全更新（不影响后续运行）
            try:
                has_git = bool(git_helper.get_os_git() or git_helper.get_git_version())
            except Exception:
                has_git = False
            if has_git:
                DEFAULT_UPSTREAM_REF = "origin/main"
                DEFAULT_UPSTREAM_REF = "origin/feat/launch-kksp993"
                upstream_ref = os.environ.get("AUTOSCRIPTOR_UPSTREAM_REF", DEFAULT_UPSTREAM_REF).strip() or DEFAULT_UPSTREAM_REF
                git_state = git_helper.begin_deploy_update(project_root, upstream_ref=upstream_ref) or {}
    except Exception:
        # 更新失败不影响主流程
        git_state = {}

    # Inside venv now
    # Optional pip index from environment variable AUTOSCRIPTOR_PIP_INDEX
    extra_index = os.environ.get("AUTOSCRIPTOR_PIP_INDEX", None)

    # Ensure venv present (no-op if already)
    ensure_venv(project_root)

    # Install dependencies
    reinstall_pip_and_install(project_root, extra_index=extra_index)

    # 根据 README 约定自动配置 MuMu（仅 Windows 有效，忽略失败）
    try:
        ensure_config_with_mumu(project_root)
    except Exception:
        pass

    # Decide run target
    target = "webui"
    if len(sys.argv) > 1:
        tgt = sys.argv[1].strip().lower()
        if tgt in {"webui", "cli", "install-only"}:
            target = tgt

    try:
        return run_target(project_root, target)
    finally:
        # 尝试恢复原始分支/提交与工作区状态
        try:
            from services.webui.server import shutdown_webui
            shutdown_webui()
            if git_helper and git_state:
                git_helper.end_deploy_update(project_root, git_state)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"安装/运行失败，退出码: {e.returncode}")
        sys.exit(e.returncode or 1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"未预期错误: {e}")
        sys.exit(1)


