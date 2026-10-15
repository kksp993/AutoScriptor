"""
WebUI 安全模块
==============
密码哈希、会话管理、速率限制、重放攻击防护，以及路由层要的那几层薄封装
（登录限流、凭据解锁 cookie、解锁校验）。独立于 server.py 以便于测试。
"""
from __future__ import annotations

import hashlib as _hashlib
import secrets as _secrets
import time as _time

from fastapi import Request
from fastapi.responses import JSONResponse

from AutoScriptor.utils.app_config import cfg
from backend.webui.api_response import api_error


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


def check_request_freshness(data: dict, max_age: int = 60) -> bool:
    """验证请求中的时间戳防止重放攻击。max_age 为允许的最大时间偏差（秒）。"""
    ts = data.get("_timestamp")
    if ts is None:
        return False
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


# ── 请求层的薄封装 ──
# 每个需要登录 / 需要解锁 / 需要限流的路由都用这几个入口，避免各处自己拼 cookie
# 名、自己数失败次数、自己决定 403 的载荷。

def is_rate_limited(ip: str) -> bool:
    return login_limiter.is_limited(ip)


def record_login_failure(ip: str) -> None:
    login_limiter.record_failure(ip)


def is_verify_rate_limited(ip: str) -> bool:
    return verify_limiter.is_limited(ip)


def record_verify_failure(ip: str) -> None:
    verify_limiter.record_failure(ip)


def credential_unlock_from_request(request: Request) -> str | None:
    return request.cookies.get(CREDENTIAL_UNLOCK_COOKIE_NAME) or request.headers.get(
        "X-Credential-Unlock"
    )


def attach_credential_unlock_cookie(response: JSONResponse, token: str) -> JSONResponse:
    response.set_cookie(
        CREDENTIAL_UNLOCK_COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        max_age=CREDENTIAL_UNLOCK_TTL,
        path="/",
    )
    return response


def clear_credential_unlock_cookie(response: JSONResponse) -> JSONResponse:
    response.delete_cookie(CREDENTIAL_UNLOCK_COOKIE_NAME, path="/")
    return response


def require_credential_unlock(request: Request) -> JSONResponse | None:
    """执行自动化前仅依据 cfg 中是否已有已解密账密判断。"""
    if cfg.has_decrypted_credentials():
        return None
    return credential_locked_response("请先验证账号密码后再执行任务")


def credential_locked_response(message: str) -> JSONResponse:
    return api_error(
        403,
        message,
        code="credential_locked",
        need_credential_unlock=True,
        need_security_key=True,
    )
