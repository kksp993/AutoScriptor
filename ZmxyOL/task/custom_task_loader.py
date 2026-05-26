"""从 data 侧 custom_task/ 目录动态加载用户 Python 任务（Nuitka 与开发模式通用）。"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_custom_task_dir
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.task_registry import task_registry
from services.core.task_tree import TaskTree

_MODULE_PREFIX = "ZmxyOL.task._ct_"


def load_custom_task_modules() -> list[str]:
    """扫描 get_custom_task_dir() 下所有 .py，动态导入并触发 @register_task。

    模块名形如 ZmxyOL.task._ct_<hash>，便于 TaskManager.reload_tasks 统一清理 ZmxyOL.*。
    """
    root = get_custom_task_dir()
    root.mkdir(parents=True, exist_ok=True)
    loaded: list[str] = []
    py_files = sorted(p for p in root.rglob("*.py") if p.name != "__init__.py")
    for py_file in py_files:
        digest = hashlib.sha256(str(py_file.resolve()).encode("utf-8")).hexdigest()[:16]
        mod_name = f"{_MODULE_PREFIX}{digest}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py_file)
            if spec is None or spec.loader is None:
                logger.error("custom_task: 无法创建 spec: %s", py_file)
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            loaded.append(mod_name)
        except Exception as e:
            logger.error("custom_task: 导入失败 %s: %s", py_file, e)
    return loaded


def prune_stale_custom_tasks() -> None:
    """删除 cfg['tasks']['自定义任务'] 下已无 TaskRegistry 对应项的叶节点（及变空的分支）。"""
    branch = cfg["tasks"].get("自定义任务")
    if not isinstance(branch, dict):
        return
    TaskTree.prune_leaves_not_in_registry(branch, "自定义任务", task_registry.has_task)
