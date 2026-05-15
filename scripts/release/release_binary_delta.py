"""
生成 bsdiff 增量补丁并输出可粘贴进 manifest 的 JSON 片段。

用法:
  python scripts/release/release_binary_delta.py create --old OLD.exe --new NEW.exe --out patch.bsdiff
  python scripts/release/release_binary_delta.py create --old OLD.exe --new NEW.exe --out patch.bsdiff --relative-path backend/autoscriptor-engine.exe --url-base https://example.com/updates/

依赖: bsdiff4（与运行环境一致）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services.core.binary_delta import create_bsdiff_patch  # noqa: E402


def cmd_create(args: argparse.Namespace) -> int:
    meta = create_bsdiff_patch(args.old, args.new, args.out)
    entry = {
        "kind": "bsdiff",
        "relative_path": args.relative_path,
        "url": "",
        "patch_sha256": meta["patch_sha256"],
        "old_sha256": meta["old_sha256"],
        "new_sha256": meta["new_sha256"],
    }
    if args.url_base:
        base = args.url_base.rstrip("/") + "/"
        name = os.path.basename(args.out)
        entry["url"] = base + name

    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="bsdiff 发布辅助")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="从旧/新文件生成补丁")
    c.add_argument("--old", required=True, help="上一版文件路径")
    c.add_argument("--new", required=True, help="当前版文件路径")
    c.add_argument("--out", required=True, help="输出的 .bsdiff 文件路径")
    c.add_argument(
        "--relative-path",
        default="path/under/install/root.bin",
        help="安装根目录下的相对路径（写入 manifest）",
    )
    c.add_argument(
        "--url-base",
        default="",
        help="可选：补丁托管 URL 前缀，将自动拼接 --out 的文件名",
    )
    c.set_defaults(func=cmd_create)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
