"""
配置文件监听器
==============
监听 config.json 的修改时间，当外部编辑后触发重载。
"""
from __future__ import annotations

import os
from datetime import datetime

from AutoScriptor.utils.logger import logger


class ConfigWatcher:
    """监听配置文件的修改时间，判断是否需要重新加载。"""

    def __init__(self, config_path: str):
        self._path = config_path
        self._last_mtime: datetime = datetime.min

    def start_watching(self):
        """记录当前修改时间作为基准"""
        self._last_mtime = self._get_mtime()

    def _get_mtime(self) -> datetime:
        try:
            ts = os.stat(self._path).st_mtime
            return datetime.fromtimestamp(ts).replace(microsecond=0)
        except OSError:
            return datetime.min

    def should_reload(self) -> bool:
        """配置文件是否在上次检查后被修改过"""
        mtime = self._get_mtime()
        if mtime > self._last_mtime:
            logger.info(f"检测到配置文件变更 ({mtime})")
            self._last_mtime = mtime
            return True
        return False
