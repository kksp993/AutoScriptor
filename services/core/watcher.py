"""
运行配置/用户脚本监听器
======================
监听 data/config.json、账号文件以及 data 侧用户脚本的修改时间，在安全边界触发重载。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from AutoScriptor.utils.logger import logger


class ConfigWatcher:
    """监听配置/用户脚本的修改时间，判断是否需要重新加载。"""

    def __init__(self, config_path: str, extra_paths: Callable[[], list[str]] | None = None):
        self._path = config_path
        self._extra_paths = extra_paths
        self._last_mtime: datetime = datetime.min
        self._seen_mtimes: dict[str, float] = {}

    def start_watching(self):
        """记录当前修改时间作为基准。"""
        self._seen_mtimes = self._snapshot_mtimes()
        self._last_mtime = self._latest_datetime(self._seen_mtimes)

    def _watched_paths(self) -> list[str]:
        paths = [self._path]
        if self._extra_paths is not None:
            paths.extend(path for path in self._extra_paths() if path)
        return paths

    def _iter_existing_paths(self):
        for raw in self._watched_paths():
            path = Path(raw)
            if not path.exists():
                continue
            yield path
            if path.is_dir():
                try:
                    yield from (p for p in path.rglob("*") if p.exists())
                except OSError:
                    continue

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve())
        except OSError:
            return str(path.absolute())

    @staticmethod
    def _same_or_under(path_key: str, root_key: str) -> bool:
        if path_key == root_key:
            return True
        try:
            Path(path_key).relative_to(Path(root_key))
            return True
        except ValueError:
            return False

    @staticmethod
    def _latest_datetime(snapshot: dict[str, float]) -> datetime:
        if not snapshot:
            return datetime.min
        return datetime.fromtimestamp(max(snapshot.values())).replace(microsecond=0)

    def _snapshot_mtimes(self) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        for path in self._iter_existing_paths():
            try:
                mtimes[self._path_key(path)] = os.stat(path).st_mtime
            except OSError:
                continue
        return mtimes

    def _get_latest_mtime(self) -> datetime:
        return self._latest_datetime(self._snapshot_mtimes())

    def mark_seen(self, paths: list[str] | None = None) -> None:
        """Mark current watcher state as already handled.

        Passing paths updates only those files/directories in the baseline.
        Scheduler uses this for its own config/account JSON writes so they do
        not immediately look like external hot-reload requests.
        """
        current = self._snapshot_mtimes()
        if paths is None:
            self._seen_mtimes = current
            self._last_mtime = self._latest_datetime(current)
            return

        roots = [Path(raw) for raw in paths if raw]
        root_keys = {self._path_key(root) for root in roots}
        for key, ts in current.items():
            if any(self._same_or_under(key, root) for root in root_keys):
                self._seen_mtimes[key] = ts
        for key in list(self._seen_mtimes.keys()):
            if any(self._same_or_under(key, root) for root in root_keys) and key not in current:
                self._seen_mtimes.pop(key, None)
        self._last_mtime = self._latest_datetime(self._seen_mtimes)

    def should_reload(self) -> bool:
        """任一监听路径是否在上次检查后被修改过。"""
        snapshot = self._snapshot_mtimes()
        changed = False
        for key, ts in snapshot.items():
            old = self._seen_mtimes.get(key)
            if old is None or ts > old:
                changed = True
                break
        if not changed:
            changed = any(key not in snapshot for key in self._seen_mtimes)

        if changed:
            mtime = self._latest_datetime(snapshot)
            logger.info(f"检测到配置/用户脚本变更 ({mtime})")
            self._seen_mtimes = snapshot
            self._last_mtime = mtime
            return True
        return False
