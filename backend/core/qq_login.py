"""Local NapCat login control. No QQ passwords, public admin tokens or message sending."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path
import re
import subprocess
from threading import RLock
import time
from typing import Callable

import requests

from backend.core import qq_bot


class LoginUnavailable(RuntimeError):
    """Safe, user-facing diagnosis; never constructed from an upstream response."""


class LoginConflict(RuntimeError):
    """An explicit choice or confirmation is required."""


class LoginStarting(LoginUnavailable):
    """The local management listener is not accepting connections yet."""


class LoginOperationFailed(LoginUnavailable):
    """Expose the failed lifecycle step, never OS exception text or process output."""

    def __init__(self, stage: str, error: Exception):
        self.stage = stage
        messages = {
            "stop": "停止旧机器人失败，尚未启动新实例；请刷新登录状态后重试",
            "start": "启动机器人失败，尚未进入 QQ 登录；请检查端口占用或本机文件权限",
        }
        message = messages[stage]
        system_code = getattr(error, "winerror", None) or getattr(error, "errno", None)
        if type(system_code) is int:
            message += f"（系统错误码 {system_code}）"
        super().__init__(message)


def validate_account(account: str) -> str:
    if not isinstance(account, str) or not re.fullmatch(r"[1-9][0-9]{4,19}", account):
        raise ValueError("请输入 5 至 20 位数字的机器人 QQ 号")
    return account


def login_error_message(error: str) -> str:
    if not error:
        return "等待 QQ 登录；新账号请扫码并在手机上确认"
    if "无法重复登录" in error or "已登录" in error:
        return "该 QQ 已被其他登录实例占用，无法重复登录。请自行退出对应桌面账号，或切换机器人账号。"
    if "过期" in error:
        return "登录二维码已过期，请点击刷新二维码"
    if "验证" in error or "新设备" in error:
        return "QQ 要求安全验证，请在手机 QQ 完成确认；未完成前不会显示登录成功"
    return "QQ 登录失败。请尝试扫码登录；不要反复重启或提供密码、Token、session。"


class LocalQQLogin:
    def __init__(self, root: Path | None = None):
        self.root = root or qq_bot.BOT_ROOT
        self._lock = RLock()
        self._session = None
        self._authenticated_at = 0.0
        self._credential_key = None
        self._process_id = None
        self._last_start = None
        self._requested_account = ""

    def close(self):
        if self._session is not None:
            self._session.close()
        self._session = None
        self._credential_key = None

    def _settings(self):
        qq_bot.assert_private_location(self.root)
        settings = qq_bot.load_local_settings(self.root)
        if settings is None:
            raise LoginUnavailable("本机机器人尚未安装，请运行 scripts\\install.bat qq")
        return settings

    def _management(self, action: str, payload: dict | None = None):
        settings = self._settings()
        configuration = qq_bot.read_document(self.root / "napcat" / "config" / "webui.json")
        token = configuration.get("token")
        if not isinstance(token, str) or not token:
            raise LoginUnavailable("机器人管理配置无效，请检查安装；不要手工填写 QQ session")
        credential_key = (settings["web_port"], hashlib.sha256(token.encode()).digest())
        base_url = f"http://127.0.0.1:{settings['web_port']}/api"
        if self._credential_key != credential_key or time.monotonic() - self._authenticated_at > 3000:
            self.close()
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False

        def post(path, body):
            try:
                response = self._session.post(
                    base_url + path, json=body, timeout=(2, 4), allow_redirects=False,
                )
                try:
                    if response.status_code != 200:
                        raise LoginUnavailable("机器人管理接口不可用，请稍后刷新登录状态")
                    document = response.json()
                finally:
                    response.close()
            except (requests.ConnectionError, requests.Timeout):
                raise LoginStarting("无法连接机器人管理接口；请先启动机器人或稍后刷新") from None
            except (requests.RequestException, ValueError):
                raise LoginUnavailable("无法连接机器人管理接口；请先启动机器人或稍后刷新") from None
            if not isinstance(document, dict) or document.get("code") != 0:
                raise LoginUnavailable("机器人拒绝管理请求；请刷新重试，勿手工填写管理令牌")
            return document.get("data")

        try:
            if self._credential_key is None:
                authentication = post("/auth/login", {
                    "hash": hashlib.sha256((token + ".napcat").encode()).hexdigest(),
                })
                if not isinstance(authentication, dict):
                    raise LoginUnavailable("机器人管理认证返回格式无效")
                if authentication.get("require2FA"):
                    raise LoginUnavailable("NapCat 管理页启用了二次验证，请先在管理页完成；本页面不会绕过验证")
                credential = authentication.get("Credential")
                if not isinstance(credential, str) or not credential or "\n" in credential or "\r" in credential:
                    raise LoginUnavailable("机器人管理认证失败")
                self._session.headers["Authorization"] = f"Bearer {credential}"
                self._credential_key = credential_key
                self._authenticated_at = time.monotonic()
            return post(action, payload or {})
        except LoginUnavailable:
            self.close()
            raise

    def status(self) -> dict:
        with self._lock:
            self._settings()
            process_id = qq_bot.bot_process_pid(self.root)
            if process_id != self._process_id:
                self.close()
                self._process_id = process_id
            result = {
                "running": process_id is not None, "logged_in": False, "account": "",
                "remembered_account": qq_bot.remembered_account(self.root),
                "requested_account": self._requested_account,
                "cached_accounts": qq_bot.cached_accounts(self.root),
                "qr_image": "", "message": "机器人尚未启动，请选择发送账号并登录",
            }
            if process_id is None:
                return result
            try:
                login = self._management("/QQLogin/CheckLoginStatus")
            except LoginStarting:
                if self._last_start is None or time.monotonic() - self._last_start > 30:
                    raise
                result["message"] = "机器人正在启动，请稍候；尚未确认 QQ 登录"
                return result
            if not isinstance(login, dict) or not isinstance(login.get("isLogin"), bool):
                raise LoginUnavailable("机器人登录状态返回格式无效，无法确认登录")
            result["logged_in"] = login["isLogin"]
            if result["logged_in"]:
                identity = self._management("/QQLogin/GetQQLoginInfo")
                if not isinstance(identity, dict):
                    raise LoginUnavailable("无法确认机器人登录账号")
                result["account"] = validate_account(str(identity.get("uin") or ""))
                result["message"] = "QQ 已登录；发送是否成功请通过测试消息确认"
                if self._requested_account and result["account"] != self._requested_account:
                    result["message"] = "实际扫码账号与所选账号不同，请切换账号；不会自动记住这个账号"
            else:
                result["message"] = login_error_message(str(login.get("loginError") or ""))
                if login.get("isOffline"):
                    result["message"] = "机器人 QQ 已离线，请重新登录"
                qr_url = login.get("qrcodeurl")
                if isinstance(qr_url, str) and qr_url and len(qr_url) <= 2048:
                    import qrcode
                    from qrcode.image.svg import SvgPathImage

                    image = qrcode.make(qr_url, image_factory=SvgPathImage)
                    buffer = BytesIO()
                    image.save(buffer)
                    result["qr_image"] = "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
            return result

    def start(
        self, account: str, method: str, *, confirm_switch: bool = False,
        on_starting: Callable[[], None] | None = None,
    ) -> dict:
        account = validate_account(account)
        if method not in ("quick", "qr"):
            raise ValueError("只支持快捷登录或扫码登录，不接收密码或 session")
        with self._lock:
            self._settings()
            if method == "quick" and account not in qq_bot.cached_accounts(self.root):
                raise ValueError("该账号没有本机登录缓存，请使用扫码登录")
            if self._last_start is not None and time.monotonic() - self._last_start < 10:
                raise LoginConflict("登录正在启动，请稍候，不要重复切换")
            process_id = qq_bot.bot_process_pid(self.root)
            if process_id is not None:
                if confirm_switch is not True:
                    raise LoginConflict("切换或重新登录会停止当前机器人，请确认；不会退出桌面 QQ")
                if not qq_bot.owns_bot_process(process_id, self.root):
                    raise LoginUnavailable("无法核验机器人进程归属，未停止任何进程")
            if on_starting is not None:
                on_starting()
            if process_id is not None:
                try:
                    qq_bot.stop_bot(self.root)
                except (OSError, subprocess.SubprocessError) as error:
                    raise LoginOperationFailed("stop", error) from None
                if qq_bot.bot_process_pid(self.root) is not None:
                    raise LoginUnavailable("机器人未完全退出，未启动第二个实例")
            self.close()
            self._requested_account = account
            self._last_start = time.monotonic()
            try:
                self._process_id = qq_bot.launch_bot(
                    self.root, account=account if method == "quick" else "", force_qr=method == "qr",
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise LoginOperationFailed("start", error) from None
            deadline = time.monotonic() + 12
            while True:
                try:
                    self._management("/QQLogin/CheckLoginStatus")
                    break
                except LoginStarting:
                    if time.monotonic() >= deadline:
                        return {"requested_account": account, "message": "机器人仍在启动，稍后请点击刷新二维码"}
                    time.sleep(0.5)
            if method == "qr":
                self._management("/QQLogin/RefreshQRcode")
            return {"requested_account": account, "message": "登录请求已提交，请确认下方实际登录账号"}

    def refresh_qr(self) -> dict:
        with self._lock:
            status = self.status()
            if not status["running"] or status["logged_in"]:
                raise LoginConflict("请先启动扫码登录；已登录时请使用切换账号")
            self._management("/QQLogin/RefreshQRcode")
            return {"message": "已请求新二维码，请稍候"}

    def remember(self, account: str) -> dict:
        account = validate_account(account)
        with self._lock:
            status = self.status()
            if not status["logged_in"] or status["account"] != account:
                raise LoginConflict("实际登录账号与确认账号不一致，未保存")
            qq_bot.remember_account(account, self.root)
            self._requested_account = ""
            return {"message": "已记住此机器人账号；没有修改接收号码或推送开关"}


local_qq_login = LocalQQLogin()
