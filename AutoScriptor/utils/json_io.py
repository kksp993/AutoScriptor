"""Durable JSON writes, with no module-level side effects.

This lives apart from :mod:`AutoScriptor.utils.app_config` on purpose. That
module builds the ``cfg`` singleton at import time and registers an ``atexit``
save, so merely importing it to reach an atomic-write helper would (a) read the
config into memory and (b) write that snapshot back over the file when the
process exits -- silently undoing a write made in between. Importing this module
instead has no such effect, which is what a setup or maintenance script needs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from AutoScriptor.logging.logger import logger


def _strict_fsync_enabled() -> bool:
    return str(os.environ.get("AUTOSCRIPTOR_STRICT_FSYNC", "")).strip().lower() in {"1", "true", "yes", "on"}


def write_json_atomic(path: Path | str, data: Any) -> None:
    """Write JSON via a same-directory temp file, then replace.

    Replace is atomic, so a crash mid-write leaves either the old file or the
    new one -- never a truncated one.
    """
    target = Path(path)
    start = time.perf_counter()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
            handle.flush()
            if _strict_fsync_enabled():
                os.fsync(handle.fileno())
        os.replace(tmp_path, target)
        elapsed = time.perf_counter() - start
        if elapsed >= 1.0:
            logger.warning("JSON 保存耗时 %.2fs: %s", elapsed, target)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
