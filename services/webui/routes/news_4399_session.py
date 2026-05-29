"""
4399 通行证会话（供资讯代理在 iframe 内拉取论坛正文）
====================================================
与 ptlogin 登录框一致：密码经 CryptoJS.AES.encrypt(..., 'lzYW5qaXVqa') 后提交 login.do。
优先使用主配置中的 news.account / news.password（专用于论坛资讯代理），否则回退到解密后的 game 账密。
默认 news 公共通行证仅用于论坛资讯代理；其他凭据必须由调用方先完成 credential_unlock。
"""
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

# cache token -> (expiry_monotonic, requests.Session)
_session_cache: dict[str, tuple[float, requests.Session]] = {}
_SESSION_TTL_SEC = 3600.0


def is_public_news_credential(account: str | None, password: str | None) -> bool:
    """项目公开 4399 资讯通行证；只允许这一组免敏感保护。"""
    return (
        (account or "").strip() == PUBLIC_NEWS_ACCOUNT
        and (password or "").strip() == PUBLIC_NEWS_PASSWORD
    )


def _evp_bytes_to_key_md5(password: bytes, salt: bytes, key_len: int, iv_len: int) -> tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey (MD5)，与 CryptoJS 默认 AES 加密一致。"""
    d = b""
    prev = b""
    need = key_len + iv_len
    while len(d) < need:
        prev = hashlib.md5(prev + password + salt).digest()
        d += prev
    return d[:key_len], d[key_len : key_len + iv_len]


def encrypt_password_for_ptlogin(plain_password: str) -> str:
    """对应 validation.js: encryptAES(IdVal)。"""
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key_md5(_AES_PASSPHRASE.encode("utf-8"), salt, 32, 16)
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain_password.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(data) + encryptor.finalize()
    out = b"Salted__" + salt + ct
    return base64.b64encode(out).decode("ascii")


def _ptlogin_form_error_message(html: str) -> str | None:
    """login.do 失败时在 #Msg 内返回错误文案；成功一般为跳转页或不含非空 Msg。"""
    m = re.search(r'<div[^>]*\bid="Msg"[^>]*>([^<]*)</div>', html or "", re.I | re.DOTALL)
    if not m:
        return None
    t = (m.group(1) or "").strip()
    return t if t else None


def login_ptlogin_session(username: str, password: str) -> requests.Session | None:
    """
    使用「账号密码登录」同款接口（ptlogin login.do + AES 密码），不处理图形验证码。
    verify.do 非 \"0\" 时仅表示前端可能插入验证码区，仍直接提交账密；若站点强制验证码则 Msg 会失败。
    """
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        return None

    s = requests.Session()
    s.headers.update(
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
        r0 = s.get(_LOGIN_FRAME, timeout=20)
        if r0.status_code != 200:
            logger.warning("news 4399: loginFrame %s", r0.status_code)
            return None

        import time as _t

        v = s.get(
            f"{_VERIFY_DO}?username={requests.utils.quote(username)}&appId=&t={int(_t.time() * 1000)}",
            timeout=15,
        )
        if v.status_code != 200:
            logger.warning("news 4399: verify.do %s", v.status_code)
            return None
        if (v.text or "").strip() not in ("0", ""):
            logger.debug(
                "news 4399: verify.do not 0 (browser 可能显示验证码区); 仍按账号密码直登 login.do"
            )

        enc_pwd = encrypt_password_for_ptlogin(password)
        form = {
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
            "password": enc_pwd,
            "iframeId": "",
            "username": username,
        }
        r1 = s.post(_LOGIN_DO, data=form, timeout=25, allow_redirects=True)
        r1.encoding = r1.apparent_encoding or "utf-8"
        if r1.status_code >= 400:
            logger.warning("news 4399: login.do HTTP %s", r1.status_code)
            return None
        err = _ptlogin_form_error_message(r1.text)
        if err:
            logger.warning("news 4399: login.do error: %s", err)
            return None
        jar = s.cookies.get_dict()
        if not jar:
            return None
        return s
    except Exception as e:
        logger.exception("news 4399: login exception: %s", e)
        return None


def get_cached_or_login_session(cache_token: str, username: str, password: str) -> requests.Session | None:
    """按调用方提供的缓存令牌缓存 Session，减少频繁登录。"""
    key = f"{cache_token}:{username}"
    now = time.monotonic()
    hit = _session_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]

    sess = login_ptlogin_session(username, password)
    if sess is not None:
        _session_cache[key] = (now + _SESSION_TTL_SEC, sess)
    return sess


def get_news_4399_credentials_from_server() -> tuple[str, str] | tuple[None, None]:
    """论坛资讯用 4399 通行证：优先 news.*；旧配置缺少 news 段时使用公开默认号。"""
    try:
        from AutoScriptor.utils.app_config import cfg

        n = cfg._config.get("news") or {}
        acc = (n.get("account") or "").strip()
        pwd = (n.get("password") or "").strip()
        if acc and pwd:
            return acc, pwd
        if "news" not in cfg._config:
            return PUBLIC_NEWS_ACCOUNT, PUBLIC_NEWS_PASSWORD

        g = cfg._config.get("game") or {}
        acc = (g.get("account") or "").strip()
        pwd = (g.get("password") or "").strip()
        if acc and pwd:
            return acc, pwd
    except Exception as e:
        logger.debug("news 4399: no creds: %s", e)
    return None, None


def get_game_credentials_from_server() -> tuple[str, str] | tuple[None, None]:
    """兼容旧名；与 get_news_4399_credentials_from_server 相同。"""
    return get_news_4399_credentials_from_server()
