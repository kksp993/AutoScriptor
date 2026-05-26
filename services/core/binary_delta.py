"""
大文件小改动的二进制增量（bsdiff4 / BSDIFF4 格式）
================================================
- 发布端：对「旧文件 + 新文件」生成 .bsdiff 补丁（体积极小常见于仅改少量字节的大 exe）。
- 客户端：在本地旧文件上应用补丁得到新文件，并校验 SHA-256。

依赖：bsdiff4（纯 Python，跨平台）。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any

try:
    import bsdiff4
except ImportError as e:  # pragma: no cover
    bsdiff4 = None  # type: ignore
    _import_error = e
else:
    _import_error = None


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_safe_path(root: str, relative_path: str) -> str:
    """
    将「安装根下的相对路径」解析为绝对路径；禁止含 .. 或跳出 root。
    """
    rel_norm = relative_path.replace("\\", "/").strip().lstrip("/")
    if ".." in rel_norm.split("/"):
        raise ValueError(f"非法 relative_path: {relative_path}")
    target = os.path.normpath(os.path.join(root, *rel_norm.split("/")))
    root_abs = os.path.abspath(root)
    tgt_abs = os.path.abspath(target)
    try:
        if os.path.commonpath([root_abs, tgt_abs]) != root_abs:
            raise ValueError(f"非法 relative_path: {relative_path}")
    except ValueError as e:
        if "非法 relative_path" in str(e):
            raise
        raise ValueError(f"非法 relative_path: {relative_path}") from None
    return target


def _ensure_bsdiff4():
    if bsdiff4 is None:
        raise RuntimeError(
            "需要安装 bsdiff4 才能使用二进制增量: pip install bsdiff4"
        ) from _import_error


def create_bsdiff_patch(old_path: str, new_path: str, patch_path: str) -> dict[str, Any]:
    """
    由旧、新文件生成 BSDIFF4 补丁文件，并返回用于写入 manifest 的元数据字段。
    """
    _ensure_bsdiff4()
    if not os.path.isfile(old_path):
        raise FileNotFoundError(f"旧文件不存在: {old_path}")
    if not os.path.isfile(new_path):
        raise FileNotFoundError(f"新文件不存在: {new_path}")

    os.makedirs(os.path.dirname(os.path.abspath(patch_path)) or ".", exist_ok=True)
    bsdiff4.file_diff(old_path, new_path, patch_path)

    old_h = sha256_file(old_path)
    new_h = sha256_file(new_path)
    patch_h = sha256_file(patch_path)

    return {
        "kind": "bsdiff",
        "old_sha256": old_h,
        "new_sha256": new_h,
        "patch_sha256": patch_h,
        "patch_bytes": os.path.getsize(patch_path),
    }


def apply_bsdiff_patch(
    old_path: str,
    patch_path: str,
    new_path: str,
    *,
    expected_new_sha256: str | None = None,
) -> None:
    """
    将补丁应用到 old_path，写入 new_path。
    若提供 expected_new_sha256，则与生成结果比对，失败则删除输出并抛错。
    """
    _ensure_bsdiff4()
    if not os.path.isfile(old_path):
        raise FileNotFoundError(f"本地旧文件不存在，无法打补丁: {old_path}")
    if not os.path.isfile(patch_path):
        raise FileNotFoundError(f"补丁文件不存在: {patch_path}")

    out_dir = os.path.dirname(os.path.abspath(new_path)) or "."
    os.makedirs(out_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".patch_out_", suffix=".tmp", dir=out_dir)
    os.close(fd)
    try:
        bsdiff4.file_patch(old_path, tmp_path, patch_path)
        if expected_new_sha256 is not None:
            got = sha256_file(tmp_path)
            if got.lower() != expected_new_sha256.lower():
                raise ValueError(
                    f"补丁结果校验失败: 期望 new_sha256={expected_new_sha256}, 得到 {got}"
                )
        os.replace(tmp_path, new_path)
    except Exception:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def atomic_write_file(path: str, data: bytes) -> None:
    """原子写入整文件（同目录临时文件 + replace）。"""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".atomic_", suffix=".tmp", dir=d)
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
