"""
生成同兼容线累计小版本更新包。

默认只打包新版 backend/autoscriptor-engine.exe，适合 1.1.0 -> 1.1.5 这类
同一 major.minor 线内的业务代码更新。依赖库、目录结构大改、Electron 壳变化应发完整安装包。

用法:
  python scripts/release/create_minor_update_package.py ^
    --new-backend dist/gui.dist ^
    --target-version 1.1.5 ^
    --out dist/AutoScriptor_Update_1.1.5.zip

额外文件:
  --include-backend services/webui/static/js/components/UpdatePanel.js
  --mkdir data/assets/cache
  --copy-if-missing path/to/template.json=data/templates/template.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

UPDATE_FORMAT = "autoscriptor_update_v1"
ENGINE_REL = "autoscriptor-engine.exe"
ENGINE_TARGET = "backend/autoscriptor-engine.exe"


def is_protected_update_path(rel: str) -> bool:
    n = normalize_rel(rel).lower()
    if n in {"data/config.json", "config.json"}:
        return True
    return (
        n.startswith("data/accounts/")
        or n.startswith("data/custom_task/")
        or n.startswith("data/battle_character/")
        or n.startswith("data/logs/")
        or n.startswith("accounts/")
        or n.startswith("custom_task/")
        or n.startswith("battle_character/")
        or n.startswith("logs/")
        or n.startswith(".autoscriptor/")
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def normalize_rel(raw: str) -> str:
    rel = raw.replace("\\", "/").strip().lstrip("/")
    if not rel or ".." in rel.split("/") or rel.startswith("/"):
        raise ValueError(f"非法相对路径: {raw}")
    return rel


def compat_line(version: str) -> str:
    parts = version.strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("--target-version 必须形如 1.1.5")
    return f"{int(parts[0])}.{int(parts[1])}"


def add_file(
    zf: zipfile.ZipFile,
    manifest_entries: list[dict],
    source: Path,
    target_rel: str,
    *,
    action: str,
) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target_rel = normalize_rel(target_rel)
    if is_protected_update_path(target_rel):
        raise ValueError(f"更新包不能写入受保护的用户数据路径: {target_rel}")
    zf.write(source, target_rel)
    manifest_entries.append(
        {
            "path": target_rel,
            "sha256": sha256_file(source),
        }
    )
    if action not in ("replace", "copy_if_missing"):
        raise ValueError(action)


def parse_copy_if_missing(raw: str) -> tuple[Path, str]:
    if "=" not in raw:
        raise ValueError("--copy-if-missing 需要 SRC=DEST")
    src, dest = raw.split("=", 1)
    return Path(src).resolve(), normalize_rel(dest)


def cmd_create(args: argparse.Namespace) -> int:
    new_backend = Path(args.new_backend).resolve()
    if not new_backend.is_dir():
        print(f"[update] 新版 backend 目录不存在: {new_backend}", file=sys.stderr)
        return 2

    target_version = args.target_version.strip()
    line = args.compat_line.strip() or compat_line(target_version)
    base_version = args.base_version.strip() or f"{line}.0"
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    replace_entries: list[dict] = []
    copy_entries: list[dict] = []
    mkdir_entries = [normalize_rel(p) for p in (args.mkdir or [])]
    for rel in mkdir_entries:
        if is_protected_update_path(rel):
            raise ValueError(f"更新包不能创建受保护的用户数据路径: {rel}")

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if not args.no_engine:
            add_file(
                zf,
                replace_entries,
                new_backend / ENGINE_REL,
                ENGINE_TARGET,
                action="replace",
            )

        for rel_raw in args.include_backend or []:
            rel = normalize_rel(rel_raw)
            add_file(
                zf,
                replace_entries,
                new_backend / rel,
                f"backend/{rel}",
                action="replace",
            )

        for raw in args.copy_if_missing or []:
            src, dest = parse_copy_if_missing(raw)
            add_file(zf, copy_entries, src, dest, action="copy_if_missing")

        config_defaults = None
        if args.config_defaults_json:
            cfg_path = Path(args.config_defaults_json).resolve()
            with cfg_path.open(encoding="utf-8") as f:
                config_defaults = json.load(f)
            if not isinstance(config_defaults, dict) or isinstance(config_defaults, list):
                raise ValueError("--config-defaults-json 必须是 JSON object")

        manifest = {
            "format": UPDATE_FORMAT,
            "compat_line": line,
            "base_version": base_version,
            "target_version": target_version,
            "mode": "minor-cumulative",
            "replace": replace_entries,
            "mkdir": mkdir_entries,
            "copy_if_missing": copy_entries,
        }
        if config_defaults:
            manifest["config_defaults"] = config_defaults
        zf.writestr("update_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    print(f"[update] 已写入: {out}")
    print(f"[update] 兼容线: {line}.x; 目标版本: {target_version}; 替换文件: {len(replace_entries)}; 补文件: {len(copy_entries)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="生成 AutoScriptor 小版本累计更新包")
    p.add_argument("--new-backend", default="dist/gui.dist", help="新版 gui.dist/backend 根目录")
    p.add_argument("--target-version", required=True, help="目标版本，如 1.1.5")
    p.add_argument("--out", required=True, help="输出 zip，如 dist/AutoScriptor_Update_1.1.5.zip")
    p.add_argument("--compat-line", default="", help="兼容线，默认由 target-version 推导，如 1.1")
    p.add_argument("--base-version", default="", help="兼容线基线，默认 x.y.0")
    p.add_argument("--no-engine", action="store_true", help="不自动纳入 autoscriptor-engine.exe")
    p.add_argument("--include-backend", action="append", default=[], help="额外纳入新版 backend 下的相对路径，可重复")
    p.add_argument("--mkdir", action="append", default=[], help="安装根下需要确保存在的目录，可重复")
    p.add_argument("--copy-if-missing", action="append", default=[], help="仅目标不存在时复制，格式 SRC=DEST，可重复")
    p.add_argument("--config-defaults-json", default="", help="要合并进 data/config.json 的默认配置 JSON，只补缺失 key")
    args = p.parse_args()
    try:
        return cmd_create(args)
    except Exception as e:
        print(f"[update] 失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
