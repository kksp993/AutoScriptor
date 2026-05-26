"""战斗流程 YAML 目录约定
====================
profiles/<职业>/流程/
  *.yaml              兼容旧版：直接放在「流程」下，视为全局可用
  通用/*.yaml         任意任务可选的通用流程
  <任务叶名>/*.yaml   仅 cfg 任务路径最后一级与目录名一致（同名任务共用）时可选

扫描顺序：先扁平 legacy，再「通用」，再其它子目录（字母序），与 load_and_compile 合并顺序一致。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import yaml

_log = logging.getLogger(__name__)


def iter_flow_yaml_files(flow_root: Path) -> Iterator[Path]:
    """单职业下「流程」目录内，按加载顺序产出所有 .yaml/.yml 路径。"""
    if not flow_root.exists():
        return
    for f in sorted(flow_root.iterdir()):
        if f.is_file() and f.suffix in (".yaml", ".yml"):
            yield f
    common = flow_root / "通用"
    if common.is_dir():
        for f in sorted(common.iterdir()):
            if f.suffix in (".yaml", ".yml"):
                yield f
    for sub in sorted(flow_root.iterdir()):
        if not sub.is_dir() or sub.name == "通用":
            continue
        for f in sorted(sub.iterdir()):
            if f.suffix in (".yaml", ".yml"):
                yield f


def yaml_top_level_keys(yaml_path: Path) -> set[str]:
    """读取 YAML 文件顶层键（流程名）。"""
    keys: set[str] = set()
    try:
        with open(yaml_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict):
            for k in data:
                if isinstance(k, str) and k.strip():
                    keys.add(k.strip())
    except Exception as e:
        _log.warning("解析流程 YAML 失败 %s: %s", yaml_path, e)
    return keys


def flow_yaml_scope_kind(yaml_path: Path, flow_root: Path) -> str | None:
    """返回 'global' 或任务叶名（子目录名）。yaml_path 须位于 flow_root 之下。"""
    try:
        rel = yaml_path.relative_to(flow_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) == 1:
        return "global"
    if len(parts) >= 2 and parts[0] == "通用":
        return "global"
    return parts[0]
