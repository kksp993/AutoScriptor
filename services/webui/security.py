"""
WebUI 安全模块
==============
密码哈希、会话管理、速率限制、重放攻击防护。
独立于 server.py 以便于测试。
"""
from __future__ import annotations

import hashlib as _hashlib
import os as _os
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

    def remaining_before_lockout(self, ip: str) -> int:
        """滑动窗口内当前失败计数下，还剩几次错误会触发限流（与 is_limited 使用相同的裁剪逻辑）。"""
        now = _time.time()
        attempts = self._failures.get(ip, [])
        attempts = [t for t in attempts if now - t < self.window]
        self._failures[ip] = attempts
        return max(0, self.max_failures - len(attempts))

    def clear(self):
        self._failures.clear()


login_limiter = RateLimiter(max_failures=5, window=300)
verify_limiter = RateLimiter(max_failures=5, window=300)


class CallRateLimiter:
    """限制某操作在窗口内的调用次数（不区分成功失败）。"""

    def __init__(self, max_calls: int = 8, window: int = 3600):
        self.max_calls = max_calls
        self.window = window
        self._calls: dict[str, list[float]] = {}

    def allow(self, ip: str) -> bool:
        now = _time.time()
        calls = [t for t in self._calls.get(ip, []) if now - t < self.window]
        if len(calls) >= self.max_calls:
            return False
        calls.append(now)
        self._calls[ip] = calls
        return True

    def clear(self):
        self._calls.clear()


class MinIntervalLimiter:
    """同一 IP 两次操作之间最短间隔（防短时间连点刷流量）。"""

    def __init__(self, min_interval_sec: float = 120.0):
        self.min_interval = min_interval_sec
        self._last: dict[str, float] = {}

    def allow(self, ip: str) -> bool:
        now = _time.time()
        last = self._last.get(ip, 0.0)
        if now - last < self.min_interval:
            return False
        self._last[ip] = now
        return True

    def clear(self):
        self._last.clear()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# 「检查更新」：默认每 IP 每小时最多 20 次（manifest 虽小仍可被刷探测）
content_update_check_limiter = CallRateLimiter(
    max_calls=max(1, int(_env_float("AUTOSCRIPTOR_CONTENT_CHECK_MAX_PER_HOUR", 20))),
    window=3600,
)

# 「应用更新」：每小时最多 5 次 / IP + 两次应用至少间隔 min_interval 秒
content_update_apply_limiter = CallRateLimiter(
    max_calls=max(1, int(_env_float("AUTOSCRIPTOR_CONTENT_APPLY_MAX_PER_HOUR", 5))),
    window=3600,
)
content_update_apply_min_interval = MinIntervalLimiter(
    min_interval_sec=_env_float("AUTOSCRIPTOR_CONTENT_APPLY_MIN_INTERVAL_SEC", 120.0),
)


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


# ── 游戏凭据解锁（安全密码）会话 ──
# 与 deploy 登录会话独立：仅凭磁盘上的 character_name 不能执行自动化，须先完成验证或带密钥切换账号。

_credential_unlock_tokens: dict[str, float] = {}
CREDENTIAL_UNLOCK_COOKIE_NAME = "credential_unlock"
CREDENTIAL_UNLOCK_TTL = 3600 * 8  # 8 小时


def _credential_cleanup_expired() -> None:
    now = _time.time()
    for k in [k for k, v in _credential_unlock_tokens.items() if v < now]:
        _credential_unlock_tokens.pop(k, None)


def grant_credential_unlock() -> str:
    """签发新的解锁令牌（写入 HttpOnly Cookie，由服务端校验）。"""
    _credential_cleanup_expired()
    tok = _secrets.token_urlsafe(32)
    _credential_unlock_tokens[tok] = _time.time() + CREDENTIAL_UNLOCK_TTL
    return tok


def validate_credential_unlock(token: str | None) -> bool:
    if not token:
        return False
    _credential_cleanup_expired()
    exp = _credential_unlock_tokens.get(token)
    if exp is None:
        return False
    if exp < _time.time():
        _credential_unlock_tokens.pop(token, None)
        return False
    return True


def revoke_credential_unlock(token: str | None) -> None:
    if token:
        _credential_unlock_tokens.pop(token, None)


def get_credential_unlock_tokens_for_tests() -> dict[str, float]:
    """仅测试用：返回内部令牌表副本"""
    return dict(_credential_unlock_tokens)
