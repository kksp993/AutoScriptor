from pathlib import Path
import subprocess


def run_target(venv_python: Path, project_root: Path, target: str) -> int:
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
