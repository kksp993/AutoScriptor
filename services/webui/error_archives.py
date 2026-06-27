"""
错误归档 WebUI：列出、详情、文件、导入 zip、删除。
与 AutoScriptor.utils.log_archiver 产出的目录结构一致。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from AutoScriptor.utils.paths import get_error_archives_dir

_RE_SAFE_FOLDER = re.compile(r"^[\w\u4e00-\u9fff.\-]+$")
_RE_FOLDER_META = re.compile(r"^(\d{6})_(\d{6})_(.+)$")
# 主日志行内时间戳（与 logger 文件格式、Rich 等常见格式兼容）
_RE_LOG_TS_FILE = re.compile(
    r"\[[A-Za-z]\s+(\d{6})\s+(\d{1,2}:\d{2}:\d{2})"
)
_RE_LOG_TS_ISO = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})"
)
# tracer 调试截图：250401_143022_123456_c.png
_RE_DBG_SHOT = re.compile(
    r"^(\d{6})_(\d{6})_(\d{6})_([cse])\.png$",
    re.IGNORECASE,
)
_RE_TIMED_SHOT = re.compile(r"^timed_screenshot_(\d+)\.png$", re.IGNORECASE)


def _safe_folder_name(name: str) -> Optional[str]:
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    if not _RE_SAFE_FOLDER.match(name):
        return None
    return name


def _resolve_archive_dir(folder: str) -> Optional[Path]:
    s = _safe_folder_name(folder)
    if not s:
        return None
    root = get_error_archives_dir()
    p = (root / s).resolve()
    try:
        root_r = root.resolve()
    except OSError:
        return None
    if p.is_dir() and (p == root_r or root_r in p.parents):
        return p
    return None


def _parse_folder_display(folder: str) -> Tuple[str, str, str]:
    """
    返回 (date_key, time_hms, task_label)。
    date_key: YYYY-MM-DD 用于分组；无法解析时用「未知日期」。
    """
    m = _RE_FOLDER_META.match(folder)
    if not m:
        return ("未知日期", "", folder)
    d, t, task = m.group(1), m.group(2), m.group(3)
    try:
        dt = datetime.strptime(d + t, "%y%m%d%H%M%S")
        date_key = dt.strftime("%Y-%m-%d")
        time_hms = dt.strftime("%H:%M:%S")
    except ValueError:
        date_key = f"20{d[:2]}-{d[2:4]}-{d[4:6]}"
        time_hms = f"{t[:2]}:{t[2:4]}:{t[4:6]}"
    return (date_key, time_hms, task.replace("_", "/"))


def list_error_archives() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    root = get_error_archives_dir()
    if root.is_dir():
        for entry in os.scandir(root):
            if not entry.is_dir():
                continue
            name = entry.name
            try:
                st = entry.stat()
                mtime = st.st_mtime
            except OSError:
                mtime = 0
            date_key, time_hms, task_label = _parse_folder_display(name)
            items.append(
                {
                    "folder": name,
                    "dateKey": date_key,
                    "timeLabel": time_hms,
                    "taskName": task_label,
                    "mtime": mtime,
                }
            )
    items.sort(key=lambda x: (-x["mtime"], x["folder"]))
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        dk = it["dateKey"]
        groups.setdefault(dk, []).append(it)
    return {"items": items, "groups": groups}


def _collect_image_paths(archive_dir: Path) -> List[str]:
    rels: List[str] = []
    for pat in ("*.png", "*.jpg", "*.jpeg"):
        for p in archive_dir.glob(pat):
            rels.append(p.name)
    click_dir = archive_dir / "click_screenshots"
    if click_dir.is_dir():
        for p in click_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
                rels.append(f"click_screenshots/{p.name}")
    rels.sort()
    return rels


def _extract_summary_from_log(text: str) -> str:
    lines = text.splitlines()
    exc_type = ""
    exc_msg = ""
    for i, line in enumerate(lines):
        if line.strip().startswith("异常类型:"):
            exc_type = line.split(":", 1)[-1].strip()
        if line.strip().startswith("异常信息:"):
            exc_msg = line.split(":", 1)[-1].strip()
    if exc_type or exc_msg:
        parts = [p for p in (exc_type, exc_msg) if p]
        return " · ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
    for line in lines:
        if "执行错误:" in line:
            return line.strip()
    return "（未能解析摘要，请查看下方日志）"


def _parse_line_log_timestamp(line: str) -> Optional[datetime]:
    """从单行日志中解析时间；无法解析则返回 None。"""
    m = _RE_LOG_TS_FILE.search(line)
    if m:
        d6, hm = m.group(1), m.group(2).replace(":", "")
        if len(hm) == 6:
            try:
                return datetime.strptime(d6 + hm, "%y%m%d%H%M%S")
            except ValueError:
                pass
    m2 = _RE_LOG_TS_ISO.search(line)
    if m2:
        try:
            return datetime.strptime(
                f"{m2.group(1)} {m2.group(2)}", "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            pass
    return None


def _folder_start_datetime(folder_name: str) -> Optional[datetime]:
    m = _RE_FOLDER_META.match(folder_name)
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    try:
        return datetime.strptime(d + t, "%y%m%d%H%M%S")
    except ValueError:
        return None


def _iter_archive_images(archive_dir: Path) -> List[Tuple[str, Path]]:
    out: List[Tuple[str, Path]] = []
    for pat in ("*.png", "*.jpg", "*.jpeg"):
        for p in archive_dir.glob(pat):
            out.append((p.name, p))
    click_dir = archive_dir / "click_screenshots"
    if click_dir.is_dir():
        for p in click_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
                out.append((f"click_screenshots/{p.name}", p))
    return out


def _image_datetime(
    rel: str,
    abs_path: Path,
    folder_name: str,
) -> Optional[datetime]:
    """从文件名、mtime、归档文件夹名推断截图时间。"""
    base = rel.split("/")[-1]
    m = _RE_DBG_SHOT.match(base)
    if m:
        d6, hm, micro, _ = m.groups()
        try:
            return datetime.strptime(d6 + hm + micro, "%y%m%d%H%M%S%f")
        except ValueError:
            pass
    m2 = _RE_TIMED_SHOT.match(base)
    if m2:
        try:
            return datetime.fromtimestamp(abs_path.stat().st_mtime)
        except OSError:
            pass
        ft = _folder_start_datetime(folder_name)
        if ft:
            try:
                idx = int(m2.group(1))
            except ValueError:
                idx = 1
            return ft + timedelta(seconds=max(0, idx))
    if base.lower() == "current_screenshot.png":
        try:
            return datetime.fromtimestamp(abs_path.stat().st_mtime)
        except OSError:
            pass
        return _folder_start_datetime(folder_name)
    try:
        return datetime.fromtimestamp(abs_path.stat().st_mtime)
    except OSError:
        return None


def _insert_after_line_index(
    image_t: datetime,
    effective_line_ts: List[Optional[datetime]],
) -> int:
    """
    返回截图应插在该行**之后**（含换行）的位置：行下标 0..n-1；-1 表示插在第一行文本之前。
    选取满足 line_effective_ts[i] <= image_t 的最大 i；若无则若早于首条时间戳则 -1。
    """
    n = len(effective_line_ts)
    best = -1
    for i in range(n):
        eff = effective_line_ts[i]
        if eff is None:
            continue
        if eff <= image_t:
            best = max(best, i)
    if best >= 0:
        return best
    for i in range(n):
        eff = effective_line_ts[i]
        if eff is not None and image_t < eff:
            return -1
    return -1


def build_log_segments(
    log_text: str,
    archive_dir: Path,
    folder_name: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    按日志行时间戳与截图时间戳对齐，生成有序 segments：text / image。
    无法对齐的截图放入 unmatched 列表（仍可在末尾展示）。
    """
    lines = log_text.splitlines()
    last: Optional[datetime] = None
    effective: List[Optional[datetime]] = []
    for line in lines:
        ts = _parse_line_log_timestamp(line)
        if ts is not None:
            last = ts
        effective.append(last)

    has_line_ts = any(t is not None for t in effective)

    raw_images = _iter_archive_images(archive_dir)
    scored: List[Tuple[str, Path, Optional[datetime]]] = []
    for rel, ap in raw_images:
        scored.append((rel, ap, _image_datetime(rel, ap, folder_name)))

    def _img_sort(t: Tuple[str, Path, Optional[datetime]]) -> Tuple[int, float]:
        rel, p, dt = t
        if dt is not None:
            return (0, dt.timestamp())
        try:
            return (1, p.stat().st_mtime)
        except OSError:
            return (2, 0.0)

    scored.sort(key=_img_sort)

    from collections import defaultdict

    by_after: Dict[int, List[str]] = defaultdict(list)
    unmatched: List[str] = []

    for rel, ap, dt in scored:
        if not has_line_ts or dt is None:
            unmatched.append(rel)
            continue
        ins = _insert_after_line_index(dt, effective)
        by_after[ins].append(rel)

    for k in by_after:
        by_after[k].sort()

    segments: List[Dict[str, Any]] = []

    if not lines:
        for rel in unmatched:
            segments.append({"type": "image", "path": rel, "unmatched": True})
        return segments, unmatched

    for rel in sorted(by_after.get(-1, [])):
        segments.append({"type": "image", "path": rel, "inline": True})

    for i, line in enumerate(lines):
        segments.append({"type": "text", "text": line + "\n"})
        for rel in sorted(by_after.get(i, [])):
            segments.append({"type": "image", "path": rel, "inline": True})

    if unmatched:
        segments.append(
            {
                "type": "text",
                "text": "\n──────── 以下截图未能与日志时间戳对齐 ────────\n",
            }
        )
        for rel in unmatched:
            segments.append({"type": "image", "path": rel, "unmatched": True})

    return segments, unmatched


def get_archive_detail(folder: str) -> Optional[Dict[str, Any]]:
    adir = _resolve_archive_dir(folder)
    if not adir:
        return None
    err_log = adir / "error.log"
    log_text = ""
    if err_log.is_file():
        try:
            log_text = err_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
    summary = _extract_summary_from_log(log_text)
    images = _collect_image_paths(adir)
    segments, unmatched_images = build_log_segments(log_text, adir, folder)

    return {
        "folder": folder,
        "summary": summary,
        "logText": log_text,
        "segments": segments,
        "unmatchedImages": unmatched_images,
        "images": images,
    }


def delete_archives(folders: List[str]) -> Dict[str, Any]:
    removed = 0
    errors: List[str] = []
    for name in folders:
        adir = _resolve_archive_dir(name)
        if not adir:
            errors.append(name)
            continue
        try:
            shutil.rmtree(adir)
            removed += 1
        except OSError as e:
            errors.append(f"{name}: {e}")
    return {"removed": removed, "errors": errors}


def import_zip_bytes(data: bytes, suggested_name: str = "import") -> Dict[str, Any]:
    """
    将 zip 解压到 logs/errors/<ts>_import_<safe>/
    要求 zip 内至少含 error.log 或任意 .log。
    """
    root = get_error_archives_dir()
    ts = datetime.now().strftime("%y%m%d_%H%M%S")
    safe = re.sub(r"[^\w\u4e00-\u9fff.\-]", "_", suggested_name)[:80] or "import"
    dest_name = f"{ts}_import_{safe}"
    dest = root / dest_name
    dest.mkdir(parents=True, exist_ok=False)

    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            zf.extractall(dest)
    except Exception as e:
        try:
            shutil.rmtree(dest)
        except OSError:
            pass
        return {"ok": False, "error": str(e)}

    has_log = any(
        p.suffix.lower() == ".log" or p.name == "error.log"
        for p in dest.rglob("*")
        if p.is_file()
    )
    if not has_log:
        try:
            shutil.rmtree(dest)
        except OSError:
            pass
        return {"ok": False, "error": "zip 内未找到 .log 或 error.log"}

    return {"ok": True, "folder": dest_name}


def read_archive_file(folder: str, rel_path: str) -> Optional[Path]:
    adir = _resolve_archive_dir(folder)
    if not adir:
        return None
    rel_path = rel_path.replace("\\", "/").strip("/")
    if ".." in rel_path or rel_path.startswith("/"):
        return None
    target = (adir / rel_path).resolve()
    if not target.is_file():
        return None
    try:
        target.relative_to(adir.resolve())
    except ValueError:
        return None
    return target
