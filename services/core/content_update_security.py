"""
内容增量更新的安全策略
====================
- 仅 HTTPS（可显式允许 HTTP 供内网调试）
- 可选主机白名单；未配置时拒绝解析到内网/回环/链路本地地址（缓解 SSRF）
- 禁止重定向；流式下载并限制体积
- 可选：manifest 整包 SHA-256
- 可选：Ed25519 签名（cryptography）

环境变量（常用）：
- AUTOSCRIPTOR_CONTENT_UPDATE_ALLOW_HTTP=1 — 允许 http（仅调试）
- AUTOSCRIPTOR_CONTENT_UPDATE_ALLOWED_HOSTS — 逗号分隔主机名；配置后仅允许这些主机并跳过 DNS 内网检测
- AUTOSCRIPTOR_CONTENT_MANIFEST_SHA256 — manifest 整文件 sha256
- AUTOSCRIPTOR_CONTENT_UPDATE_PUBLIC_KEY_PEM / AUTOSCRIPTOR_CONTENT_UPDATE_PUBLIC_KEY_PATH
- AUTOSCRIPTOR_CONTENT_MAX_MANIFEST_BYTES / _MAX_PATCH_BYTES / _MAX_RAW_BYTES
- AUTOSCRIPTOR_SHELL_VERSION — 与 manifest.min_shell_version 比对（若两者均配置）
- AUTOSCRIPTOR_CONTENT_UPDATE_REQUIRE_CREDENTIAL_UNLOCK=1 — 应用更新前要求安全凭据解锁
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

import requests

# ── 默认上限（可通过环境变量覆盖）──

DEFAULT_MAX_MANIFEST_BYTES = 2 * 1024 * 1024  # 2 MiB
DEFAULT_MAX_PATCH_BYTES = 650 * 1024 * 1024  # 650 MiB（大 exe 的补丁上限）
DEFAULT_MAX_RAW_BYTES = 80 * 1024 * 1024  # 80 MiB 单个小文件


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def max_manifest_bytes() -> int:
    return max(64 * 1024, _env_int("AUTOSCRIPTOR_CONTENT_MAX_MANIFEST_BYTES", DEFAULT_MAX_MANIFEST_BYTES))


def max_patch_bytes() -> int:
    return max(1024 * 1024, _env_int("AUTOSCRIPTOR_CONTENT_MAX_PATCH_BYTES", DEFAULT_MAX_PATCH_BYTES))


def max_raw_bytes() -> int:
    return max(1024, _env_int("AUTOSCRIPTOR_CONTENT_MAX_RAW_BYTES", DEFAULT_MAX_RAW_BYTES))


def allow_insecure_http() -> bool:
    return os.environ.get("AUTOSCRIPTOR_CONTENT_UPDATE_ALLOW_HTTP", "").strip() in (
        "1",
        "true",
        "yes",
    )


def _allowed_hosts_from_env() -> set[str] | None:
    raw = os.environ.get("AUTOSCRIPTOR_CONTENT_UPDATE_ALLOWED_HOSTS", "").strip()
    if not raw:
        return None
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _host_allowed(hostname: str, allowlist: set[str] | None) -> bool:
    h = hostname.lower().strip(".")
    if not allowlist:
        return True
    for entry in allowlist:
        e = entry.lower().strip(".")
        if h == e or h.endswith("." + e):
            return True
    return False


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved:
        return True
    # 文档 / 本地用
    if ip.version == 4 and ip in ipaddress.ip_network("0.0.0.0/8"):
        return True
    return False


def assert_url_safe_for_download(url: str) -> None:
    """
    校验 URL 方案与主机；未配置白名单时拒绝解析到不可路由/内网地址。
    """
    p = urlparse(url)
    if p.scheme not in ("https", "http"):
        raise ValueError(f"不支持的 URL 协议: {url}")
    if p.scheme == "http" and not allow_insecure_http():
        raise ValueError("仅允许 HTTPS 下载（或设置 AUTOSCRIPTOR_CONTENT_UPDATE_ALLOW_HTTP=1 用于调试）")
    if not p.netloc:
        raise ValueError(f"非法 URL: {url}")

    host = p.hostname
    if host is None:
        raise ValueError(f"无法解析主机名: {url}")

    allowlist = _allowed_hosts_from_env()
    if allowlist is not None and not _host_allowed(host, allowlist):
        raise ValueError(f"主机不在允许列表中: {host}")

    # 仅白名单时跳过 IP 检测（用户已明确信任这些主机）
    if allowlist is not None:
        return

    # 尝试解析 IP
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            raise ValueError(f"禁止访问该地址: {host}")
        return
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"DNS 解析失败，拒绝下载: {host}") from e

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise ValueError(f"主机 {host} 解析到不可信地址: {addr}")


def fetch_bytes_limited(
    url: str,
    max_bytes: int,
    expected_sha256: str | None,
    timeout: int = 300,
) -> bytes:
    """GET 下载，禁止重定向，限制体积，可选 SHA-256。"""
    assert_url_safe_for_download(url)
    from services.core.binary_delta import sha256_bytes

    headers = {"Accept-Encoding": "identity"}
    with requests.get(
        url,
        timeout=timeout,
        stream=True,
        allow_redirects=False,
        headers=headers,
    ) as r:
        r.raise_for_status()

        cl = r.headers.get("Content-Length")
        if cl is not None:
            try:
                n = int(cl)
                if n > max_bytes:
                    raise ValueError(f"资源过大: Content-Length={n} > {max_bytes}")
            except ValueError as e:
                if "资源过大" in str(e):
                    raise
                pass

        chunks: list[bytes] = []
        total = 0
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"下载超过上限 {max_bytes} 字节")
            chunks.append(chunk)
        data = b"".join(chunks)

    if expected_sha256:
        got = sha256_bytes(data)
        if got.lower() != expected_sha256.lower():
            raise ValueError(f"校验失败: 期望 sha256={expected_sha256}, 得到 {got}")
    return data


def verify_manifest_sha256_if_configured(
    raw_manifest_bytes: bytes,
    expected_hex: str | None = None,
) -> None:
    """若配置了整包 SHA-256（参数或环境变量），则校验。"""
    expected = (expected_hex or "").strip().lower() or os.environ.get(
        "AUTOSCRIPTOR_CONTENT_MANIFEST_SHA256", ""
    ).strip().lower()
    if not expected:
        return
    from services.core.binary_delta import sha256_bytes

    got = sha256_bytes(raw_manifest_bytes)
    if got.lower() != expected:
        raise ValueError(f"manifest SHA-256 与配置不一致: 期望 {expected}, 得到 {got}")


def manifest_bytes_for_signing(manifest: dict[str, Any]) -> bytes:
    """与签名脚本使用相同的 canonical 序列（不含签名字段）。"""
    drop = {"signature_ed25519", "signature"}
    m2 = {k: v for k, v in manifest.items() if k not in drop}
    return json.dumps(m2, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode('utf-8')


def verify_manifest_ed25519_if_configured(
    manifest: dict[str, Any],
    public_key_pem: str | None = None,
    public_key_path: str | None = None,
) -> None:
    """
    若配置了公钥（参数、环境变量或 PEM 文件路径），则要求 manifest 含 signature_ed25519（base64）。
    """
    pem = (public_key_pem or "").strip() or os.environ.get(
        "AUTOSCRIPTOR_CONTENT_UPDATE_PUBLIC_KEY_PEM", ""
    ).strip()
    path = (public_key_path or "").strip() or os.environ.get(
        "AUTOSCRIPTOR_CONTENT_UPDATE_PUBLIC_KEY_PATH", ""
    ).strip()
    if not pem and path:
        if not os.path.isfile(path):
            raise ValueError(f"公钥文件不存在: {path}")
        pem = open(path, encoding="utf-8").read()
    if not pem:
        return

    sig_b64 = manifest.get("signature_ed25519")
    if not isinstance(sig_b64, str) or not sig_b64.strip():
        raise ValueError("已配置公钥，manifest 必须包含 signature_ed25519")

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization
    except ImportError as e:
        raise RuntimeError("需要 cryptography 以校验 Ed25519 签名") from e

    try:
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    except Exception as e:
        raise ValueError("公钥 PEM 无效") from e
    if not isinstance(pub, Ed25519PublicKey):
        raise ValueError("公钥必须是 Ed25519")

    try:
        sig = base64.b64decode(sig_b64.strip(), validate=True)
    except Exception as e:
        raise ValueError("signature_ed25519 不是合法 base64") from e

    payload = manifest_bytes_for_signing(manifest)
    try:
        pub.verify(sig, payload)
    except Exception as e:
        raise ValueError("manifest Ed25519 签名无效") from e


def _hex_sha256(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", s))


def validate_manifest_artifact_hashes(manifest: dict[str, Any]) -> None:
    """强制校验条目中哈希格式，防止异常值。"""
    arts = manifest.get("artifacts")
    if not isinstance(arts, list):
        raise ValueError("manifest 缺少 artifacts 数组")
    for i, art in enumerate(arts):
        if not isinstance(art, dict):
            raise ValueError(f"artifacts[{i}] 非法")
        kind = art.get("kind")
        if kind == "bsdiff":
            for key in ("old_sha256", "new_sha256", "patch_sha256"):
                v = art.get(key)
                if not isinstance(v, str) or not _hex_sha256(v):
                    raise ValueError(f"artifacts[{i}] {key} 必须是 64 位十六进制 SHA-256")
        elif kind == "raw":
            v = art.get("sha256")
            if not isinstance(v, str) or not _hex_sha256(v):
                raise ValueError(f"artifacts[{i}] sha256 必须是 64 位十六进制 SHA-256")
        else:
            raise ValueError(f"artifacts[{i}] 未知 kind")


def verify_min_shell_version_if_present(manifest: dict[str, Any]) -> None:
    """若 manifest 含 min_shell_version 且环境变量 AUTOSCRIPTOR_SHELL_VERSION 已设置，则比对。"""
    req = manifest.get("min_shell_version")
    if not isinstance(req, str) or not req.strip():
        return
    cur = os.environ.get("AUTOSCRIPTOR_SHELL_VERSION", "").strip()
    if not cur:
        return
    try:
        from packaging.version import parse as pv
        if pv(cur) < pv(req.strip()):
            raise ValueError(
                f"当前安装包版本 {cur} 低于要求 {req.strip()}，请下载新版安装程序"
            )
    except Exception as e:
        if "低于要求" in str(e):
            raise
        pass


def apply_security_checks_after_parse(
    manifest: dict[str, Any],
    *,
    public_key_pem: str | None = None,
    public_key_path: str | None = None,
) -> None:
    """解析 manifest 后：Ed25519、条目哈希格式、可选 shell 版本。"""
    verify_min_shell_version_if_present(manifest)
    verify_manifest_ed25519_if_configured(
        manifest,
        public_key_pem=public_key_pem,
        public_key_path=public_key_path,
    )
    validate_manifest_artifact_hashes(manifest)
