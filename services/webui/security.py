"""
WebUI 安全模块
==============
密码哈希、会话管理、速率限制、重放攻击防护。
独立于 server.py 以便于测试。
"""
from __future__ import annotations

import hashlib as _hashlib
import secrets as _secrets
import time as _time


# ── 密码哈希 ──

def hash_deploy_password(raw: str) -> str:
    """使用 PBKDF2-SHA256 对 WebUI 访问密码进行哈希"""
    salt = _secrets.token_hex(16)
    dk = _hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_deploy_password(raw: str, stored: str) -> bool:
    """验证密码。兼容旧版明文存储和新版哈希格式。"""
    if not stored:
        return False
    if not stored.startswith("pbkdf2$"):
        return _secrets.compare_digest(raw, stored)
    parts = stored.split("$", 2)
    if len(parts) != 3:
        return False
    _, salt, expected_hex = parts
    dk = _hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return _secrets.compare_digest(dk.hex(), expected_hex)


# ── 会话管理 ──

_sessions: dict[str, float] = {}
SESSION_TTL = 86400  # 24 小时


def create_session() -> str:
    """创建随机会话令牌并返回"""
    token = _secrets.token_urlsafe(32)
    _sessions[token] = _time.time() + SESSION_TTL
    cutoff = _time.time()
    for k in [k for k, v in _sessions.items() if v < cutoff]:
        _sessions.pop(k, None)
    return token


def validate_session(token: str | None) -> bool:
    """验证会话令牌是否有效"""
    if not token:
        return False
    exp = _sessions.get(token)
    if exp is None:
        return False
    if exp < _time.time():
        _sessions.pop(token, None)
        return False
    return True


def get_sessions() -> dict[str, float]:
    """返回内部会话字典（仅测试用）"""
    return _sessions


# ── 速率限制 ──

class RateLimiter:
    """基于滑动窗口的 IP 速率限制器"""

    def __init__(self, max_failures: int = 5, window: int = 300):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, list[float]] = {}

    def is_limited(self, ip: str) -> bool:
        now = _time.time()
        attempts = self._failures.get(ip, [])
        attempts = [t for t in attempts if now - t < self.window]
        self._failures[ip] = attempts
        return len(attempts) >= self.max_failures

    def record_failure(self, ip: str):
        self._failures.setdefault(ip, []).append(_time.time())

    def clear(self):
        self._failures.clear()


login_limiter = RateLimiter(max_failures=5, window=300)
verify_limiter = RateLimiter(max_failures=5, window=300)


# ── 重放攻击防护 ──

def check_request_freshness(data: dict, max_age: int = 60) -> bool:
    """验证请求中的时间戳防止重放攻击。max_age 为允许的最大时间偏差（秒）。"""
    ts = data.get("_timestamp")
    if ts is None:
        return True  # 向后兼容：旧客户端不发时间戳时放行
    try:
        return abs(_time.time() - float(ts)) <= max_age
    except (ValueError, TypeError):
        return False
