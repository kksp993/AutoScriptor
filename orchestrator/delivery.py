"""Everything that leaves the process: toasts, push channels, OneBot QQ, reports.

One module because callers need one thing -- tell someone what happened -- and the
transports behind it are interchangeable. Nothing here reads the task tree or owns
scheduling state, so the scheduler and the WebUI can both publish results without
depending on each other.

Ordered by layer:

- transports: the bounded OneBot FIFO worker.
- run reports: per-character aggregation that turns outcomes into one message.
- local channels: Windows toast and onepush providers.
"""
from __future__ import annotations

import os
import subprocess
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import Lock, Thread
from typing import Callable
from urllib.parse import urlsplit

import requests

from AutoScriptor.logging.logger import logger


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


CharacterKey = tuple[str, str]


@dataclass
class CharacterReport:
    character: CharacterKey
    position: int | None = None
    outcomes: dict[str, tuple[str, str]] = field(default_factory=dict)

    def format_message(self, *, interrupted: bool = False) -> str:
        server, name = self.character
        success_count = sum(state == "success" for _, state in self.outcomes.values())
        failed_count = sum(state == "failed" for _, state in self.outcomes.values())
        interrupted = interrupted or any(state == "pending" for _, state in self.outcomes.values())
        status = "已中断" if interrupted else ("部分失败" if failed_count else "任务完成")
        prefix = f"{self.position}:" if self.position is not None else ""
        lines = [f"{prefix}({name}){status}-成功:{success_count},失败:{failed_count}"]
        labels = {"success": "完成", "failed": "失败", "pending": "未完成"}
        details = [f"{path.rsplit('/', 1)[-1]}{labels[state]}" for path, state in self.outcomes.values()]
        lines.append("、".join(details[:6]) + (f" 等{len(details)}项" if len(details) > 6 else ""))
        failed_tasks = [path for path, state in self.outcomes.values() if state == "failed"]
        if failed_tasks:
            lines.append("失败项: " + "、".join(failed_tasks[:5]))
        if server:
            lines.append(f"服务器: {server}")
        return "\n".join(lines)


class CharacterReports:
    def __init__(self, publish: Callable[[str], None], order: list[CharacterKey]):
        self._publish = publish
        self._positions = {character: position for position, character in enumerate(order, 1)}
        self._reports: dict[CharacterKey, CharacterReport] = {}

    def record(self, character: CharacterKey, run_id: str, task_path: str, state: str) -> None:
        if state not in ("success", "failed", "pending"):
            raise ValueError(f"Invalid task outcome: {state}")
        report = self._reports.setdefault(character, CharacterReport(character, self._positions.get(character)))
        # A successful retry replaces its failed attempt; it is not a second task.
        report.outcomes[run_id] = (task_path, state)

    def flush_ready(self, current: CharacterKey, pending_retries: set[CharacterKey]) -> None:
        for character in list(self._reports):
            if character != current and character not in pending_retries:
                self._publish(self._reports.pop(character).format_message())

    def finish(self, *, interrupted: bool = False) -> None:
        for report in self._reports.values():
            self._publish(report.format_message(interrupted=interrupted))
        self._reports.clear()


def create_character_reports(settings_payload: dict, order: list[CharacterKey]) -> CharacterReports:
    """Bind the optional QQ sink once; all execution hooks remain transport-neutral."""
    try:
        settings = QQSettings.parse(settings_payload)
    except ValueError as error:
        logger.error("QQ notification configuration invalid: %s", error)
        return CharacterReports(lambda message: None, order)
    return CharacterReports(lambda message: qq_notifier.submit(settings, message), order)


def handle_notify(config_yaml: str, title: str = "", content: str = "") -> bool:
    """
    发送通知推送。

    Args:
        config_yaml: YAML 格式的 onepush 配置字符串，至少包含 provider 字段
        title: 通知标题
        content: 通知内容

    Returns:
        bool: 是否发送成功
    """
    try:
        import yaml
        from onepush import get_notifier
        from onepush.core import Provider
        from onepush.providers.custom import Custom
    except ImportError:
        logger.warning("onepush 未安装，跳过通知推送 (pip install onepush)")
        return False

    try:
        config = {}
        for item in yaml.safe_load_all(config_yaml):
            if item is None:
                continue
            if not isinstance(item, dict):
                logger.error("通知配置必须是 YAML 映射，跳过发送")
                return False
            config.update(item)
    except yaml.YAMLError:
        logger.error("通知配置解析失败，跳过发送")
        return False

    try:
        provider_name = config.pop("provider", None)
        if not provider_name:
            return False

        notifier: Provider = get_notifier(provider_name)
        required = notifier.params.get("required", [])

        config["title"] = title
        config["content"] = content

        for key in required:
            if key not in config:
                logger.warning(f"通知 {notifier.name} 缺少必需参数 '{key}'")

        if isinstance(notifier, Custom):
            if config.get("method", "post") == "post":
                config["datatype"] = "json"
            if "data" not in config or not isinstance(config.get("data"), dict):
                config["data"] = {}
            config["data"]["title"] = title
            config["data"]["content"] = content

        if provider_name.lower() == "gocqhttp":
            access_token = config.get("access_token")
            if access_token:
                config["token"] = access_token

        resp = notifier.notify(**config)

        if hasattr(resp, "status_code"):
            if resp.status_code != 200:
                logger.warning(f"通知推送失败: HTTP {resp.status_code}")
                return False
            if provider_name.lower() == "gocqhttp":
                data = resp.json()
                if data.get("status") == "failed":
                    logger.warning(f"通知推送失败: {data.get('wording', '')}")
                    return False

    except Exception as e:
        logger.error(f"通知推送异常: {e}")
        return False

    logger.info("通知推送成功")
    return True


def notify_desktop(title: str, content: str) -> bool:
    """发送 Windows 右下角 Toast；非 Windows 环境直接跳过。"""
    if os.name != "nt":
        return False
    script = r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$template = @"
<toast><visual><binding template="ToastGeneric"><text></text><text></text></binding></visual></toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$texts = $xml.GetElementsByTagName("text")
$texts.Item(0).AppendChild($xml.CreateTextNode($env:AUTOSCRIPTOR_TOAST_TITLE)) > $null
$texts.Item(1).AppendChild($xml.CreateTextNode($env:AUTOSCRIPTOR_TOAST_CONTENT)) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("AutoScriptor").Show($toast)
'''
    env = os.environ.copy()
    env["AUTOSCRIPTOR_TOAST_TITLE"] = title
    env["AUTOSCRIPTOR_TOAST_CONTENT"] = content
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).check_returncode()
    except Exception as e:
        logger.warning("Windows 桌面通知失败: %s", e)
        return False
    return True


def notify_from_config(title: str, content: str) -> bool:
    """从全局配置读取通知设置并发送"""
    from AutoScriptor.utils.app_config import cfg
    if not cfg.get("notify.enabled", False):
        return False
    config_yaml = cfg.get("notify.config_yaml", "provider: null")
    return handle_notify(config_yaml, title=title, content=content)


def notify_runtime_event(title: str, content: str) -> bool:
    """同步发送本机桌面通知，并沿用用户配置的远程通知。"""
    desktop_ok = notify_desktop(title, content)
    config_ok = notify_from_config(title, content)
    return desktop_ok or config_ok
