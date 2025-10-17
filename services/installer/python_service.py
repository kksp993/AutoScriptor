import os
import subprocess
from pathlib import Path

class PythonService:
    def __init__(self, env_config, download_service, project_config):
        self.env_config = env_config
        self.download_service = download_service
        self.project_config = project_config

    def install_standalone_python(self, version):
        zip_name = f"cpython-{version}.zip"
        return self.download_service.download_and_extract(zip_name, self.env_config.env_source, self.env_config.python_dir)

    def create_venv(self, python_exe, venv_dir):
        # python_exe should be path to python.exe
        subprocess.check_call([python_exe, "-m", "venv", venv_dir])
        return True

    def pip_install_requirements(self, venv_python, requirements_txt=None, wheels_dir=None, extra_index=None):
        # 使用 python -m pip 升级 pip、setuptools、wheel
        subprocess.check_call([venv_python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        # 安装依赖
        if wheels_dir:
            subprocess.check_call([venv_python, "-m", "pip", "install", "--no-index", "--find-links", wheels_dir, "-r", requirements_txt])
        else:
            cmd = [venv_python, "-m", "pip", "install", "-r", requirements_txt]
            if extra_index:
                cmd += ["-i", extra_index]
            subprocess.check_call(cmd)
        return True 