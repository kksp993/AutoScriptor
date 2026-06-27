"""Source-run path helpers.

The src branch keeps one durable runtime shape:

- app root: repository root
- source data root: app root, unless AUTOSCRIPTOR_DATA_DIR is set
- editable data: data/ under the app root, unless AUTOSCRIPTOR_DATA_DIR is set
- global config: editable data root/config.json

AUTOSCRIPTOR_DATA_DIR remains supported for tests and external source data roots.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_app_root() -> Path:
    """Repository root."""
    return Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def get_data_root() -> Path:
    """Source asset/log root."""
    env_override = os.environ.get("AUTOSCRIPTOR_DATA_DIR")
    if env_override:
        return Path(env_override).resolve()
    return get_app_root()


def get_editable_data_root() -> Path:
    """Editable runtime data root for accounts, custom tasks and battle scripts."""
    if os.environ.get("AUTOSCRIPTOR_DATA_DIR"):
        return get_data_root()
    return get_app_root() / "data"


def get_config_path() -> Path:
    """Mutable source runtime config."""
    return get_editable_data_root() / "config.json"


def get_custom_task_dir() -> Path:
    """User custom task scripts."""
    return get_editable_data_root() / "custom_task"


def get_accounts_dir() -> Path:
    """Account JSON directory."""
    return get_editable_data_root() / "accounts"


@lru_cache(maxsize=1)
def get_logs_root() -> Path:
    """Writable logs directory."""
    root = get_data_root() / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_error_archives_dir() -> Path:
    """Task error archive directory."""
    path = get_logs_root() / "errors"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_battle_character_dir() -> Path:
    """Editable battle character scripts."""
    return get_editable_data_root() / "battle_character"


def get_assets_dir() -> Path:
    """Source ZmxyOL asset directory."""
    return get_data_root() / "ZmxyOL" / "assets"


def get_static_dir() -> Path:
    """WebUI static directory."""
    return get_app_root() / "services" / "webui" / "static"


def get_vendor_dir() -> Path:
    """WebUI vendor directory."""
    return get_app_root() / "services" / "webui" / "vendor"
