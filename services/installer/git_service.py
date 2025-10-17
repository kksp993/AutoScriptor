import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

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

    # —— 安全更新与恢复 ——
    def _git(self, work_dir: Path, *args: str, capture: bool = False) -> str:
        git_exe = self.get_os_git() or self.env_config.git_path
        cmd = [git_exe, "-C", str(work_dir), *args]
        if capture:
            return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        subprocess.check_call(cmd)
        return ""

    def _current_branch(self, work_dir: Path) -> str | None:
        name = self._git(work_dir, "rev-parse", "--abbrev-ref", "HEAD", capture=True)
        return None if name == "HEAD" else name

    def _head_sha(self, work_dir: Path) -> str:
        return self._git(work_dir, "rev-parse", "HEAD", capture=True)

    def _status_porcelain(self, work_dir: Path) -> str:
        return self._git(work_dir, "status", "--porcelain", capture=True)

    def _has_uncommitted(self, work_dir: Path) -> bool:
        return bool(self._status_porcelain(work_dir))

    def _create_tag(self, work_dir: Path, name: str) -> None:
        # 强制指向当前 HEAD（不影响远端）
        self._git(work_dir, "tag", "-f", name, "HEAD")

    def _create_stash(self, work_dir: Path, message: str) -> str | None:
        # 根据环境变量决定是否包含被忽略文件
        include_ignored = str(os.environ.get("AUTOSCRIPTOR_STASH_INCLUDE_IGNORED", "0")).lower() not in {"", "0", "false", "no"}
        stash_flags = ["-a"] if include_ignored else ["-u"]

        # 当包含 ignored 时，可能 status 仍为空，这里也尝试执行一次 push；Git 若无可保存内容会返回无变更
        try:
            if include_ignored or self._has_uncommitted(work_dir):
                self._git(work_dir, "stash", "push", *stash_flags, "-m", message)
        except subprocess.CalledProcessError:
            # 忽略 stash push 的异常（例如确实没有需要保存的变更）
            pass
        # 找到刚创建的 stash 记录（通过消息匹配）
        out = self._git(work_dir, "stash", "list", "--format=%H %gd %gs", capture=True)
        for line in out.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3 and parts[2] == message:
                return parts[1]  # 如 stash@{0}
        # 兜底：返回栈顶
        top = self._git(work_dir, "stash", "list", "--format=%gd", capture=True)
        return top.splitlines()[0] if top else None

    def _checkout_or_create_deploy(self, work_dir: Path, upstream_ref: str) -> None:
        # 创建/切换到本地 deploy 分支，并设置上游为 origin/main
        branches = self._git(work_dir, "branch", "--list", "deploy", capture=True)
        if branches:
            self._git(work_dir, "checkout", "deploy")
        else:
            self._git(work_dir, "checkout", "-b", "deploy")
        # 设置上游（若已设置不会报错）
        try:
            self._git(work_dir, "branch", f"--set-upstream-to={upstream_ref}", "deploy")
        except subprocess.CalledProcessError:
            pass

    def _ensure_branch_from_upstream(self, work_dir: Path, branch: str, upstream: str) -> None:
        # 确保本地分支存在，若不存在则基于上游创建并跟踪
        exists = self._git(work_dir, "branch", "--list", branch, capture=True)
        if exists:
            self._git(work_dir, "checkout", branch)
        else:
            # 若上游存在则创建跟踪分支，否则仅创建本地分支
            try:
                self._git(work_dir, "checkout", "-b", branch, "--track", upstream)
            except subprocess.CalledProcessError:
                self._git(work_dir, "checkout", "-b", branch)

    def begin_deploy_update(self, project_root, upstream_ref: str = "origin/main") -> dict:
        """安全地切到 deploy 并与 origin/main 对齐，返回可用于恢复的状态。"""
        work_dir = Path(project_root)
        if not (work_dir / ".git").exists():
            return {}

        original_branch = self._current_branch(work_dir)
        original_head = self._head_sha(work_dir)
        status_before = self._status_porcelain(work_dir)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        tag_name = f"autoscriptor/pre-update/{timestamp}"
        self._create_tag(work_dir, tag_name)

        stash_msg = f"autoscriptor:auto-update-prestate:{timestamp}"
        stash_ref = self._create_stash(work_dir, stash_msg)

        # 切到 deploy 并更新到指定上游（只影响本地 deploy）
        self._git(work_dir, "fetch", "--all", "--prune")
        self._checkout_or_create_deploy(work_dir, upstream_ref)
        self._git(work_dir, "reset", "--hard", upstream_ref)

        return {
            "original_branch": original_branch,
            "original_head": original_head,
            "status_before": status_before,
            "tag_name": tag_name,
            "stash_ref": stash_ref,
        }

    def end_deploy_update(self, project_root, state: dict) -> None:
        """从 deploy 返回原始分支并恢复修改/暂存状态与文件内容。"""
        work_dir = Path(project_root)
        if not (work_dir / ".git").exists():
            return

        original_branch = state.get("original_branch")
        original_head = state.get("original_head")
        tag_name = state.get("tag_name")
        stash_ref = state.get("stash_ref")

        # 确定重放目标分支：
        # - 若原始分支存在且不是 deploy，则回到原始分支，并恢复到原始提交
        # - 若原始分支为 deploy（误在 deploy 运行），则切回 main，并保证存在/跟踪 origin/main
        if original_branch and original_branch != "deploy":
            self._git(work_dir, "checkout", original_branch)
            if original_head:
                self._git(work_dir, "reset", "--hard", original_head)
        else:
            # 回到 main；若不存在则创建并追踪 origin/main
            self._git(work_dir, "fetch", "--all", "--prune")
            self._ensure_branch_from_upstream(work_dir, "main", "origin/main")
            # 不强制 reset --hard，避免覆盖用户 main 上既有工作；如需可按需开启

        # 恢复 stash，包含 index（保持原「已暂存/未暂存」状态）
        if stash_ref:
            try:
                self._git(work_dir, "stash", "apply", "--index", stash_ref)
                # 清理该条 stash 记录
                self._git(work_dir, "stash", "drop", stash_ref)
            except subprocess.CalledProcessError:
                # 若应用失败，不强制 drop，留待人工处理
                pass

        # 清理临时 tag（不影响远端）
        if tag_name:
            try:
                self._git(work_dir, "tag", "-d", tag_name)
            except subprocess.CalledProcessError:
                pass

    def update_main_via_deploy(self, project_root, upstream_ref: str = "origin/main") -> None:
        """方便调用：仅将本地 deploy 同步到 origin/main，不切回。"""
        work_dir = Path(project_root)
        if not (work_dir / ".git").exists():
            return
        self._git(work_dir, "fetch", "--all", "--prune")
        self._checkout_or_create_deploy(work_dir, upstream_ref)
        self._git(work_dir, "reset", "--hard", upstream_ref)
        