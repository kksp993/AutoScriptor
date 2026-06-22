"""
统一路径解析模块
================
为开发模式 (python gui.py) 和编译模式 (Nuitka standalone) 提供一致的路径 API。

在开发模式下:
  APP_ROOT  = 项目根目录 (包含 gui.py 的目录)
  DATA_ROOT = 项目根目录 (config.json, ZmxyOL/assets/ 等)
  EDITABLE_DATA_ROOT = 项目根目录 / data (accounts/, custom_task/, battle_character/ 等)

在 Nuitka standalone 编译后:
  APP_ROOT  = 安装目录 (造笔.exe 所在目录)
  DATA_ROOT = APP_ROOT / data  (用户可编辑数据)

环境变量 AUTOSCRIPTOR_DATA_DIR 可覆盖 DATA_ROOT (Electron main.js 会设置此变量)。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from functools import lru_cache


def is_compiled() -> bool:
    """当前是否运行在 Nuitka 编译后的二进制中。"""
    # 须在模块 globals 上检测：函数内 dir() 无参时只含局部名，不含 __compiled__
    if "__compiled__" in globals():
        return True
    # 少数环境下子模块未注入 __compiled__；用引擎 exe 名区分「python gui.py」与 standalone
    try:
        if Path(sys.executable).resolve().name.lower() == "autoscriptor-engine.exe":
            return True
    except OSError:
        pass
    return False


@lru_cache(maxsize=1)
def get_app_root() -> Path:
    """应用根目录。

    - 编译模式: gui.dist/ 所在目录的父级 (即安装目录)
    - 开发模式: 项目根目录 (包含 gui.py)
    """
    env_override = os.environ.get("AUTOSCRIPTOR_APP_ROOT")
    if env_override:
        return Path(env_override).resolve()
    if is_compiled():
        return Path(sys.executable).resolve().parent.parent
    # 开发模式: paths.py -> AutoScriptor/utils/ -> AutoScriptor/ -> 项目根
    return Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def get_data_root() -> Path:
    """主数据根目录 (config.json, profiles 等)。

    优先使用环境变量 AUTOSCRIPTOR_DATA_DIR (Electron 启动时设置)。
    """
    env_override = os.environ.get("AUTOSCRIPTOR_DATA_DIR")
    if env_override:
        return Path(env_override).resolve()
    if is_compiled():
        return get_app_root() / "data"
    return get_app_root()


def get_editable_data_root() -> Path:
    """运行态可编辑数据根目录。

    开发模式也集中到项目根目录 data/，避免账号/自定义任务/职业覆盖脚本散落在源码根。
    发行模式与 AUTOSCRIPTOR_DATA_DIR 仍沿用 get_data_root()。
    """
    if os.environ.get("AUTOSCRIPTOR_DATA_DIR") or is_compiled():
        return get_data_root()
    return get_app_root() / "data"


def get_custom_task_dir() -> Path:
    """用户自定义任务脚本目录 (各 .py 内使用 @register_task)。

    开发模式: 项目根目录下 data/custom_task/
    发行模式: data/custom_task/（或 AUTOSCRIPTOR_DATA_DIR/custom_task/）
    """
    return get_editable_data_root() / "custom_task"


def get_accounts_dir() -> Path:
    """账号数据目录（真实账号 JSON 不进入 Git / Nuitka 内置包）。"""
    return get_editable_data_root() / "accounts"


@lru_cache(maxsize=1)
def get_engine_root() -> Path:
    """引擎文件目录 (编译后的 .pyd/.dll 所在处)。

    - 编译模式: gui.dist/ 目录
    - 开发模式: 项目根目录
    """
    if is_compiled():
        return Path(sys.executable).resolve().parent
    return get_app_root()


@lru_cache(maxsize=1)
def get_logs_root() -> Path:
    """日志目录 (始终可写)。"""
    root = get_data_root() / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_error_archives_dir() -> Path:
    """任务错误归档目录 (与 log_archiver.archive_error 写入位置一致)。"""
    d = get_logs_root() / "errors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_profiles_dir() -> Path:
    """已弃用：旧 YAML 配招目录。职业逻辑请改 data/battle_character。"""
    if is_compiled():
        return get_data_root() / "profiles"
    return get_data_root() / "ZmxyOL" / "assets" / "profiles"


def get_battle_character_dir() -> Path:
    """运行态可编辑战斗职业 .py 目录（开发与发行均为 data/battle_character）。"""
    return get_editable_data_root() / "battle_character"


def get_assets_dir() -> Path:
    """ZmxyOL 资源目录 (ui_map.csv, pic/ 等)。"""
    if is_compiled():
        return get_data_root() / "assets"
    return get_data_root() / "ZmxyOL" / "assets"


def get_static_dir() -> Path:
    """WebUI 静态文件目录。"""
    if is_compiled():
        return get_engine_root() / "services" / "webui" / "static"
    return get_app_root() / "services" / "webui" / "static"


def get_vendor_dir() -> Path:
    """WebUI vendor 目录。"""
    if is_compiled():
        return get_engine_root() / "services" / "webui" / "vendor"
    return get_app_root() / "services" / "webui" / "vendor"
