import os
import shutil
import subprocess
from pathlib import Path

DOT_GIT_DIR = lambda work_dir: os.path.join(work_dir, ".git")

class GitService:
    def __init__(self, env_config, download_service, project_config):
        self.env_config = env_config
        self.download_service = download_service
        self.project_config = project_config

    def get_os_git(self):
        try:
            out = subprocess.check_output(["where", "git"], shell=True, stderr=subprocess.DEVNULL)
            path = out.decode().splitlines()[0].strip()
            if path.endswith(".exe"):
                return path
        except Exception:
            return None

    def install_default_git(self):
        # 若系统已有 git 则跳过
        if self.get_git_version() is not None:
            return True
        zip_name = "MinGit.zip"
        return self.download_service.download_and_extract(zip_name, self.env_config.env_source, self.env_config.git_path)

    def get_git_version(self):
        try:
            out = subprocess.check_output([self.env_config.git_path, "--version"], stderr=subprocess.DEVNULL)
            return out.decode().strip()
        except Exception:
            return None

    def clone_or_update(self, repo_url, work_dir):
        work_dir = Path(work_dir)
        git_exe = self.get_os_git() or self.env_config.git_path
        if not (work_dir / ".git").exists():
            # clone 到临时，再替换/移动以减少中断
            tmp = work_dir.parent / ".temp_clone"
            if tmp.exists():
                shutil.rmtree(tmp)
            subprocess.check_call([git_exe, "clone", "--depth", "1", repo_url, str(tmp)])
            # move contents
            if work_dir.exists():
                shutil.rmtree(work_dir)
            tmp.rename(work_dir)
            return True
        else:
            subprocess.check_call([git_exe, "-C", str(work_dir), "fetch", "--all"])
            subprocess.check_call([git_exe, "-C", str(work_dir), "reset", "--hard", "origin/main"])
            return True