"""OneBot HTTP transport and bounded, best-effort background delivery.

This module does not import the scheduler, game runtime, or global config.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
import logging
from threading import Lock, Thread
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QQSettings:
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:3000"
    target_type: str = "private"
    target_id: str = ""
    access_token: str = field(default="", repr=False)

    @classmethod
    def parse(cls, payload: dict, *, require_target: bool = False) -> QQSettings:
        if not isinstance(payload, dict):
            raise ValueError("QQ settings must be an object")
        settings = cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})
        if not isinstance(settings.enabled, bool):
            raise ValueError("enabled must be a boolean")
        for key in ("endpoint", "target_type", "target_id", "access_token"):
            if not isinstance(getattr(settings, key), str):
                raise ValueError(f"{key} must be a string")
        if settings.target_type not in ("private", "group"):
            raise ValueError("target_type must be private or group")
        endpoint = settings.endpoint.strip().rstrip("/")
        try:
            parsed = urlsplit(endpoint)
            valid_port = parsed.port is None or parsed.port > 0
        except ValueError:
            raise ValueError("Invalid OneBot HTTP address") from None
        if (
            parsed.scheme not in ("http", "https") or not parsed.hostname or not valid_port
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(character.isspace() for character in endpoint)
        ):
            raise ValueError("Use an HTTP(S) service address without credentials, query or fragment")
        target_id = settings.target_id.strip()
        if len(target_id) > 20:
            raise ValueError("QQ / group number is too long")
        if target_id and (not target_id.isascii() or not target_id.isdigit() or int(target_id) <= 0):
            raise ValueError("QQ / group number must be a positive integer")
        if (settings.enabled or require_target) and not target_id:
            raise ValueError("QQ / group number is required")
        if any(character in settings.access_token for character in "\r\n"):
            raise ValueError("Access token must not contain line breaks")
        if not settings.access_token.isascii():
            raise ValueError("Access token must contain only ASCII characters")
        return cls(settings.enabled, endpoint, settings.target_type, target_id, settings.access_token.strip())

    def public_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("access_token")
        payload["token_set"] = bool(self.access_token)
        return payload


class DeliveryError(RuntimeError):
    """A safe error message which never includes credentials or response bodies."""


def send_message(settings: QQSettings, message: str) -> None:
    headers = {"Authorization": f"Bearer {settings.access_token}"} if settings.access_token else {}
    target_key = "group_id" if settings.target_type == "group" else "user_id"
    try:
        response = requests.post(
            f"{settings.endpoint}/send_{settings.target_type}_msg",
            headers=headers,
            json={
                target_key: int(settings.target_id),
                # Explicit text segments prevent names/task text from becoming CQ commands.
                "message": [{"type": "text", "data": {"text": message}}],
            },
            timeout=(3, 5),
            allow_redirects=False,
        )
    except requests.Timeout:
        raise DeliveryError("QQ 接口超时；未自动重发，请先检查 QQ，避免重复通知") from None
    except requests.RequestException:
        raise DeliveryError("无法连接 QQ 接口，请检查地址、证书和机器人服务") from None
    try:
        if response.status_code != 200:
            raise DeliveryError(f"QQ 接口返回 HTTP {response.status_code}，请检查服务地址和令牌")
        try:
            payload = response.json()
        except ValueError:
            raise DeliveryError("QQ 接口未返回 OneBot JSON") from None
        if not isinstance(payload, dict):
            raise DeliveryError("QQ 接口返回格式无效")
        if payload.get("status") != "ok" or type(payload.get("retcode")) is not int or payload["retcode"] != 0:
            raise DeliveryError("OneBot 未确认发送成功，请检查机器人登录、好友或群权限及服务日志")
        message_data = payload.get("data")
        if not isinstance(message_data, dict) or message_data.get("message_id") is None:
            raise DeliveryError("OneBot 未返回消息编号，无法确认发送结果")
    finally:
        response.close()


class QQNotifier:
    """One FIFO worker; snapshots never read a subsequently switched character/config."""

    def __init__(self):
        self._lock = Lock()
        self._pending = deque()
        self._history = deque(maxlen=20)
        self._worker: Thread | None = None

    def history(self) -> list[dict]:
        with self._lock:
            return [dict(record) for record in reversed(self._history)]

    def _record(self, message: str, success: bool, error: str = "") -> dict:
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "message": message, "success": success, "error": error,
        }
        with self._lock:
            self._history.append(record)
        if not success:
            logger.warning("QQ notification failed: %s", error)
        return record

    def deliver(self, settings: QQSettings, message: str) -> dict:
        try:
            send_message(settings, message)
        except DeliveryError as error:
            return self._record(message, False, str(error))
        return self._record(message, True)

    def submit(self, settings: QQSettings, message: str) -> None:
        if not settings.enabled:
            return
        error = ""
        with self._lock:
            if len(self._pending) >= 100:
                error = "QQ 发送队列已满，本条未发送"
            else:
                self._pending.append((settings, message))
                if self._worker is None:
                    self._worker = Thread(target=self._drain, name="QQNotifier", daemon=True)
                    try:
                        self._worker.start()
                    except RuntimeError:
                        self._worker = None
                        self._pending.pop()
                        error = "QQ 发送线程未能启动，本条未发送"
        if error:
            self._record(message, False, error)

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                settings, message = self._pending.popleft()
            try:
                self.deliver(settings, message)
            except Exception as error:
                # This is the external delivery boundary, not a task failure/retry.
                self._record(message, False, f"通知发送异常 ({type(error).__name__})")


qq_notifier = QQNotifier()
