"""Path resolution for the AutoScriptor runtime.

AutoScriptor owns exactly one configuration file and its log tree. Where task
scripts, character data or account files live is decided by the caller, so this
module exposes no game-specific directory.

Source-run layout:

- app root: the repository (or install) root
- data root: the app root, unless ``AUTOSCRIPTOR_DATA_DIR`` is set
- config: ``<data root>/config.json``, or ``<app root>/data/config.json``
- logs: ``<data root>/logs``

The asset tree (UI map csv, reference images) lives outside this package so a
consumer can point it at its own content. Register it with
``set_assets_root()``; until then :func:`get_assets_dir` falls back to the
in-repo default.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional


# Asset tree holder. ``None`` means "use the packaged default".
_assets_root: Optional[Path] = None


@lru_cache(maxsize=1)
def get_app_root() -> Path:
    """Repository (or installation) root."""
    return Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def get_data_root() -> Path:
    """Runtime data root."""
    env_override = os.environ.get("AUTOSCRIPTOR_DATA_DIR")
    if env_override:
        return Path(env_override).resolve()
    return get_app_root()


def get_config_path() -> Path:
    """The single AutoScriptor configuration file."""
    if os.environ.get("AUTOSCRIPTOR_DATA_DIR"):
        return get_data_root() / "config.json"
    return get_app_root() / "data" / "config.json"


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


def set_assets_root(path: Path | str | None) -> None:
    """Point the asset tree at ``path``; ``None`` restores the default."""
    global _assets_root
    _assets_root = Path(path) if path is not None else None


def get_assets_dir() -> Path:
    """Asset tree holding ``config/ui_map.csv`` and ``pic/``.

    Returns the tree registered through :func:`set_assets_root`, or the in-repo
    default when nothing was registered.
    """
    if _assets_root is not None:
        return _assets_root
    return get_data_root() / "assets"
