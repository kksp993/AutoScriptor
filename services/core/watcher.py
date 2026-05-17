"""
运行配置/用户脚本监听器
======================
监听 config.json、账号文件以及 data 侧用户脚本的修改时间，在安全边界触发重载。
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

    def start_watching(self):
        """记录当前修改时间作为基准。"""
        self._last_mtime = self._get_latest_mtime()

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

    def _get_latest_mtime(self) -> datetime:
        mtimes = []
        for path in self._iter_existing_paths():
            try:
                ts = os.stat(path).st_mtime
                mtimes.append(datetime.fromtimestamp(ts).replace(microsecond=0))
            except OSError:
                continue
        return max(mtimes, default=datetime.min)

    def should_reload(self) -> bool:
        """任一监听路径是否在上次检查后被修改过。"""
        mtime = self._get_latest_mtime()
        if mtime > self._last_mtime:
            logger.info(f"检测到配置/用户脚本变更 ({mtime})")
            self._last_mtime = mtime
            return True
        return False
