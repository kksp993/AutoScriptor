"""
生成 backend 文件级增量包（小体积），供已安装用户升级而无需重新下载完整 backend.zip。

与完整包关系:
  - 完整 dist/backend.zip：首次安装 / 基线不匹配时的全量解压（install-packaged.cjs 现有逻辑）。
  - 增量 dist/backend_incremental.zip：仅含变更文件 + incremental_manifest.json；由 install-packaged 的
    applyBackendIncremental 应用到已有 backend/ 目录（校验旧文件 SHA-256 后覆盖）。

用法:
  python scripts/release/release_backend_incremental.py create \\
    --old path/to/old_gui.dist 或 old_backend.zip \\
    --new dist/gui.dist \\
    --out dist/backend_incremental.zip

可选:
  --from-label 1.0.0 --to-label 1.0.1   # 写入 manifest，便于分发说明
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _sha256_zip_member(zf: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with zf.open(name, "r") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _collect_from_dir(root: Path) -> dict[str, str]:
    """相对路径 posix -> sha256"""
    out: dict[str, str] = {}
    if not root.is_dir():
        raise NotADirectoryError(root)
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            fp = Path(dirpath) / name
            rel = fp.relative_to(root).as_posix()
            out[rel] = _sha256_file(fp)
    return out


def _collect_from_zip(zip_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            n = name.replace("\\", "/").strip("/")
            if ".." in n.split("/"):
                raise ValueError(f"非法 zip 路径: {name}")
            out[n] = _sha256_zip_member(zf, name)
    return out


def _collect_old(old: Path) -> dict[str, str]:
    if old.is_dir():
        return _collect_from_dir(old)
    if old.is_file() and old.suffix.lower() == ".zip":
        return _collect_from_zip(old)
    raise FileNotFoundError(f"--old 须为目录或 .zip 文件: {old}")


def create_incremental(
    old: Path,
    new_root: Path,
    out_zip: Path,
    from_label: str = "",
    to_label: str = "",
) -> dict:
    old_map = _collect_old(old)
    new_map = _collect_from_dir(new_root)

    old_paths = set(old_map.keys())
    new_paths = set(new_map.keys())

    removed = sorted(old_paths - new_paths)
    entries: list[dict] = []

    for rel in sorted(new_paths):
        new_h = new_map[rel]
        if rel not in old_map:
            entries.append(
                {
                    "path": rel,
                    "action": "add",
                    "new_sha256": new_h,
                }
            )
        elif old_map[rel] != new_h:
            entries.append(
                {
                    "path": rel,
                    "action": "replace",
                    "old_sha256": old_map[rel],
                    "new_sha256": new_h,
                }
            )

    manifest = {
        "format": "backend_incremental_v1",
        "from_label": from_label or None,
        "to_label": to_label or None,
        "entries": entries,
        "remove": removed,
    }

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    n_payload = 0
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        zf.writestr("incremental_manifest.json", manifest_bytes)
        new_root_res = new_root.resolve()
        for e in entries:
            rel = e["path"]
            fp = new_root_res / rel
            if not fp.is_file():
                raise FileNotFoundError(f"新版缺少文件: {fp}")
            zf.write(fp, rel)
            n_payload += 1

    total_old = len(old_map)
    total_new = len(new_map)
    unchanged = total_new - len([e for e in entries if e["action"] in ("add", "replace")])
    return {
        "manifest": manifest,
        "out_zip": str(out_zip),
        "payload_files": n_payload,
        "removed": len(removed),
        "unchanged_files": unchanged,
        "stats_old_files": total_old,
        "stats_new_files": total_new,
    }


def cmd_create(args: argparse.Namespace) -> int:
    old = Path(args.old).resolve()
    new_root = Path(args.new).resolve()
    out = Path(args.out).resolve()
    if not new_root.is_dir():
        print(f"[incremental] 错误: --new 不是目录: {new_root}", file=sys.stderr)
        return 2
    try:
        summary = create_incremental(
            old,
            new_root,
            out,
            from_label=args.from_label or "",
            to_label=args.to_label or "",
        )
    except Exception as e:
        print(f"[incremental] 失败: {e}", file=sys.stderr)
        return 1

    m = summary["manifest"]
    n_ent = len(m["entries"])
    n_rm = len(m["remove"])
    print(f"[incremental] 已写入: {out}")
    print(
        f"[incremental] 变更: 新增/替换 {n_ent} 个文件, 删除 {n_rm} 个;"
        f" 旧版文件数 {summary['stats_old_files']}, 新版 {summary['stats_new_files']}"
    )
    if n_ent == 0 and n_rm == 0:
        print("[incremental] 提示: 与旧版完全一致，增量包仍已生成（仅含 manifest），客户端应用时无文件变更。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="backend 文件级增量包（对比旧 gui.dist 或旧 backend.zip）")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="生成 backend_incremental.zip")
    c.add_argument("--old", required=True, help="旧版 gui.dist 目录，或旧 backend.zip")
    c.add_argument("--new", required=True, help="新版 gui.dist 目录（通常为 dist/gui.dist）")
    c.add_argument("--out", required=True, help="输出路径，如 dist/backend_incremental.zip")
    c.add_argument("--from-label", default="", help="可选：起始版本说明")
    c.add_argument("--to-label", default="", help="可选：目标版本说明")
    c.set_defaults(func=cmd_create)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
