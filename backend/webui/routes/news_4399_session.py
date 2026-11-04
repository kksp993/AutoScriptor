"""4399 ptlogin session helpers for the news/forum proxy."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import time

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

_PTLOGIN_ORIGIN = "https://ptlogin.4399.com"
_LOGIN_FRAME = f"{_PTLOGIN_ORIGIN}/ptlogin/loginFrame.do?postLoginHandler=default"
_LOGIN_DO = f"{_PTLOGIN_ORIGIN}/ptlogin/login.do?v=1"
_VERIFY_DO = f"{_PTLOGIN_ORIGIN}/ptlogin/verify.do"
_AES_PASSPHRASE = "lzYW5qaXVqa"
PUBLIC_NEWS_ACCOUNT = "85rwm3janyyc"
PUBLIC_NEWS_PASSWORD = "123456"

_session_cache: dict[str, tuple[float, requests.Session]] = {}
_SESSION_TTL_SEC = 3600.0


class News4399LoginError(RuntimeError):
    """An upstream login failure that must remain visible to news consumers."""


def is_public_news_credential(account: str | None, password: str | None) -> bool:
    """Return True for the one public 4399 news credential allowed in this repo."""
    return (
        (account or "").strip() == PUBLIC_NEWS_ACCOUNT
        and (password or "").strip() == PUBLIC_NEWS_PASSWORD
    )


def _evp_bytes_to_key_md5(password: bytes, salt: bytes, key_len: int, iv_len: int) -> tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey with MD5, matching CryptoJS default AES output."""
    data = b""
    previous = b""
    need = key_len + iv_len
    while len(data) < need:
        previous = hashlib.md5(previous + password + salt).digest()
        data += previous
    return data[:key_len], data[key_len : key_len + iv_len]


def encrypt_password_for_ptlogin(plain_password: str) -> str:
    """Encrypt a ptlogin password like validation.js encryptAES(IdVal)."""
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key_md5(_AES_PASSPHRASE.encode("utf-8"), salt, 32, 16)
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain_password.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return base64.b64encode(b"Salted__" + salt + ciphertext).decode("ascii")


def _ptlogin_form_error_message(html: str) -> str | None:
    match = re.search(r'<div[^>]*\bid="Msg"[^>]*>([^<]*)</div>', html or "", re.I | re.DOTALL)
    if not match:
        return None
    text = (match.group(1) or "").strip()
    return text if text else None


def login_ptlogin_session(username: str, password: str) -> requests.Session | None:
    """Login through ptlogin login.do and return a requests session."""
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        return None

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": _LOGIN_FRAME,
        }
    )

    try:
        frame_response = session.get(_LOGIN_FRAME, timeout=20)
        if frame_response.status_code != 200:
            raise News4399LoginError(f"4399 登录页请求失败（HTTP {frame_response.status_code}）。")

        verify_response = session.get(
            f"{_VERIFY_DO}?username={requests.utils.quote(username)}&appId=&t={int(time.time() * 1000)}",
            timeout=15,
        )
        if verify_response.status_code != 200:
            raise News4399LoginError(f"4399 登录验证请求失败（HTTP {verify_response.status_code}）。")
        if (verify_response.text or "").strip() not in ("0", ""):
            logger.debug("news 4399: verify.do requested captcha; trying direct login.do anyway")

        response = session.post(
            _LOGIN_DO,
            data={
                "loginFrom": "uframe",
                "postLoginHandler": "default",
                "layoutSelfAdapting": "true",
                "externalLogin": "",
                "displayMode": "",
                "layout": "vertical",
                "bizId": "",
                "appId": "",
                "gameId": "",
                "css": "",
                "redirectUrl": "",
                "sessionId": "",
                "mainDivId": "embed_login_div",
                "includeFcmInfo": "false",
                "level": "0",
                "regLevel": "0",
                "sec": "1",
                "password": encrypt_password_for_ptlogin(password),
                "iframeId": "",
                "username": username,
            },
            timeout=25,
            allow_redirects=True,
        )
        response.encoding = response.apparent_encoding or "utf-8"
        # 202 may contain only "please try later" and initialization cookies, not a login.
        if response.status_code != 200:
            if response.status_code in (202, 429):
                raise News4399LoginError(
                    f"4399 暂未接受自动登录（HTTP {response.status_code}），请稍后重试，或在浏览器中打开论坛原文。"
                )
            raise News4399LoginError(f"4399 自动登录请求失败（HTTP {response.status_code}）。")
        error = _ptlogin_form_error_message(response.text)
        if error:
            raise News4399LoginError("4399 未完成登录，请在浏览器中确认账号状态或完成验证码。")
        if not session.cookies.get_dict():
            raise News4399LoginError("4399 登录未返回会话，请稍后重试。")
        return session
    except News4399LoginError:
        session.close()
        raise
    except requests.RequestException as error:
        session.close()
        raise News4399LoginError("连接 4399 登录服务失败，请检查网络后重试。") from error


def get_cached_session(cache_token: str, username: str) -> requests.Session | None:
    """Return a still-valid cached session without triggering login."""
    key = f"{cache_token}:{username}"
    now = time.monotonic()
    hit = _session_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    if hit:
        _session_cache.pop(key, None)
    return None


def get_cached_or_login_session(
    cache_token: str,
    username: str,
    password: str,
    *,
    force: bool = False,
) -> requests.Session | None:
    """Return a cached session or create a new ptlogin session."""
    key = f"{cache_token}:{username}"
    now = time.monotonic()
    if not force:
        hit = _session_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        if hit:
            _session_cache.pop(key, None)
    else:
        _session_cache.pop(key, None)

    session = login_ptlogin_session(username, password)
    if session is not None:
        _session_cache[key] = (now + _SESSION_TTL_SEC, session)
    return session


def get_news_4399_credentials_from_server() -> tuple[str, str] | tuple[None, None]:
    """Return configured news credentials or the public default when news config is absent."""
    try:
        from AutoScriptor.utils.app_config import cfg

        news_cfg = cfg._config.get("news") or {}
        account = (news_cfg.get("account") or "").strip()
        password = (news_cfg.get("password") or "").strip()
        if account and password:
            return account, password
        if "news" not in cfg._config:
            return PUBLIC_NEWS_ACCOUNT, PUBLIC_NEWS_PASSWORD

        game_cfg = cfg._config.get("game") or {}
        account = (game_cfg.get("account") or "").strip()
        password = (game_cfg.get("password") or "").strip()
        if account and password:
            return account, password
    except Exception as e:
        logger.debug("news 4399: no creds: %s", e)
    return None, None
