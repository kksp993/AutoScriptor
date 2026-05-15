"""
配置文件监听器
==============
监听 config.json 的修改时间，当外部编辑后触发重载。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Callable

from AutoScriptor.utils.logger import logger


class ConfigWatcher:
    """监听配置文件的修改时间，判断是否需要重新加载。"""

    def __init__(self, config_path: str, extra_paths: Callable[[], list[str]] | None = None):
        self._path = config_path
        self._extra_paths = extra_paths
        self._last_mtime: datetime = datetime.min

    def start_watching(self):
        """记录当前修改时间作为基准"""
        self._last_mtime = self._get_latest_mtime()

    def _watched_paths(self) -> list[str]:
        paths = [self._path]
        if self._extra_paths is not None:
            paths.extend(path for path in self._extra_paths() if path)
        return paths

    def _get_latest_mtime(self) -> datetime:
        mtimes = []
        for path in self._watched_paths():
            try:
                ts = os.stat(path).st_mtime
                mtimes.append(datetime.fromtimestamp(ts).replace(microsecond=0))
            except OSError:
                continue
        return max(mtimes, default=datetime.min)

    def should_reload(self) -> bool:
        """配置文件是否在上次检查后被修改过"""
        mtime = self._get_latest_mtime()
        if mtime > self._last_mtime:
            logger.info(f"检测到配置文件变更 ({mtime})")
            self._last_mtime = mtime
            return True
        return False
