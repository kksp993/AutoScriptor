# 基本路径与下载源配置
import os
from enum import Enum

REPO_NAME = "AutoScriptor"

# 以当前文件位置推导项目根（AutoScriptor/installer → 项目根）
_THIS_DIR = os.path.abspath(os.path.dirname(__file__))
WORK_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
DEFAULT_ENV_PATH = os.path.join(WORK_DIR, ".installer_cache")
DEFAULT_GIT_DIR_PATH = os.path.join(WORK_DIR, "install", "MinGit")
DEFAULT_PYTHON_DIR_PATH = os.path.join(WORK_DIR, "install", "cpython")
DEFAULT_VENV_DIR_PATH = os.path.join(WORK_DIR, ".venv")

class PipSourceEnum(Enum):
    PYPI = "https://pypi.org/simple"
    CUSTOM = "https://your.internal/pypi"

class EnvConfig:
    def __init__(self):
        self.env_source = ""  # 可选：自定义 MinGit/cpython 存放地址（留空表示不自动下载）
        self.is_gh_proxy = False
        self.gh_proxy_url = ""
        self.personal_proxy = None
        self.git_path = os.path.join(DEFAULT_GIT_DIR_PATH, "bin", "git.exe")
        self.uv_path = os.path.join(WORK_DIR, "install", "uv", "uv.exe")
        self.pip_source = PipSourceEnum.PYPI.value