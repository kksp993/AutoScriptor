"""
为 content manifest 生成 Ed25519 签名（发布端使用）。

1. 生成密钥对（一次性）:
   python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; from cryptography.hazmat.primitives import serialization as s; k=Ed25519PrivateKey.generate(); print(k.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode()); print(k.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo).decode())"

2. 签名:
   python scripts/sign_content_manifest.py --manifest manifest.json --private-key key.pem -o manifest-signed.json

客户端在 config 或环境中配置公钥后，仅信任带有效签名的 manifest。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys

REPO_ROOT = __import__("os").path.abspath(
    __import__("os").path.join(__import__("os").path.dirname(__file__), "..")
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services.core.content_update_security import manifest_bytes_for_signing  # noqa: E402


def main() -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    p = argparse.ArgumentParser(description="为 manifest 添加 signature_ed25519")
    p.add_argument("--manifest", required=True, help="未签名的 manifest.json")
    p.add_argument("--private-key", required=True, help="Ed25519 私钥 PEM 文件")
    p.add_argument("-o", "--output", help="输出路径（默认覆盖输入）")
    args = p.parse_args()

    with open(args.manifest, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        print("manifest 根必须是对象", file=sys.stderr)
        return 1

    pem = open(args.private_key, encoding="utf-8").read()
    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        print("私钥必须是 Ed25519", file=sys.stderr)
        return 1

    payload = manifest_bytes_for_signing(data)
    sig = key.sign(payload)
    data["signature_ed25519"] = base64.b64encode(sig).decode("ascii")

    out = args.output or args.manifest
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
