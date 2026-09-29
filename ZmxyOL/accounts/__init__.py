"""Locations of the account domain's files.

Everything here derives from the AutoScriptor configuration location, so
relocating the runtime with ``AUTOSCRIPTOR_DATA_DIR`` moves these directories
along with it. The ``assets`` tree lives inside the ``ZmxyOL`` package and is
registered with AutoScriptor so its UI map and reference images resolve
without the framework knowing about this package.
"""
from __future__ import annotations

from pathlib import Path

from AutoScriptor.utils.paths import get_config_path, set_assets_root


def get_editable_data_root() -> Path:
    """Directory holding the mutable data tree."""
    return get_config_path().parent


def get_accounts_dir() -> Path:
    """Account JSON directory."""
    return get_editable_data_root() / "accounts"


def get_custom_task_dir() -> Path:
    """User custom task scripts."""
    return get_editable_data_root() / "custom_task"


def get_character_dir() -> Path:
    """Editable character scripts."""
    return get_editable_data_root() / "character"


def get_assets_dir() -> Path:
    """UI map csv, reference images and other game assets."""
    return Path(__file__).resolve().parent.parent / "assets"


def register_assets_root() -> None:
    """Point AutoScriptor's UI map loader at this package's asset tree."""
    set_assets_root(get_assets_dir())
