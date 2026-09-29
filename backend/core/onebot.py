"""Minimal OneBot v11 HTTP client.

Everything the QQ notification flow needs from a OneBot implementation, and
nothing else: check whether the bot is up and logged in, list the targets a user
could send to, and deliver one message. Works against the local managed NapCat
and against any external OneBot service, because the protocol is the same.

Deliberately narrow:

- HTTP only. The event stream (WebSocket / SSE / HTTP POST) is not needed here;
  nothing in this project reacts to incoming messages during normal operation.
- One attempt per call. A retry loop belongs to the caller that knows whether the
  failure is worth retrying.
- The access token never appears in an exception message or a log line.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# OneBot answers in milliseconds; anything slower is a broken service, not a
# slow one, and the caller would rather see the failure than wait.
DEFAULT_TIMEOUT = 10.0


class OneBotError(RuntimeError):
    """The service refused the call, or could not be reached at all."""


def call(
    endpoint: str,
    access_token: str = "",
    action: str = "",
    payload: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """POST one action and return the decoded reply.

    Raises :class:`OneBotError` for a transport failure or a non-zero ``retcode``.
    Callers that treat "not logged in yet" as normal should use
    :func:`probe_login` instead, which returns ``None`` rather than raising.
    """
    base = str(endpoint or "").rstrip("/")
    if not base or not action:
        raise OneBotError("endpoint 和 action 都不能为空")

    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = Request(
        f"{base}/{action}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers=headers,
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8", "replace"))
    except HTTPError as error:
        # 401 means the token is wrong; that is worth saying plainly, because it
        # is the one mistake a user makes by hand.
        if error.code == 401:
            raise OneBotError("访问令牌不正确（HTTP 401）") from None
        raise OneBotError(f"OneBot 返回 HTTP {error.code}") from None
    except URLError as error:
        raise OneBotError(f"连不上 OneBot：{error.reason}") from None
    except (OSError, ValueError) as error:
        raise OneBotError(f"OneBot 响应无法解析：{error}") from None

    if not isinstance(document, dict):
        raise OneBotError("OneBot 响应不是 JSON 对象")
    retcode = document.get("retcode")
    if retcode != 0:
        message = str(document.get("message") or document.get("wording") or "").strip()
        raise OneBotError(f"OneBot 拒绝执行 {action}（retcode={retcode}）：{message}")
    return document


def probe_login(endpoint: str, access_token: str = "", timeout: float = 5.0) -> dict[str, Any] | None:
    """Return the logged-in account, or ``None`` when the bot is not ready yet.

    "Not ready" covers every normal state during startup and before someone has
    finished logging in, so it must not raise.
    """
    try:
        document = call(endpoint, access_token, "get_login_info", timeout=timeout)
    except OneBotError:
        return None
    account = document.get("data")
    if not isinstance(account, dict) or not account.get("user_id"):
        return None
    return account


def list_recipients(endpoint: str, access_token: str = "") -> list[dict[str, str]]:
    """Everything this bot could send to, as pickable options.

    Friends come first: a private message is what most people want, and a fresh
    bot account usually has exactly one friend -- the person receiving the
    notifications -- so the first entry is a sensible default.
    """
    options: list[dict[str, str]] = []

    try:
        friends = call(endpoint, access_token, "get_friend_list").get("data") or []
    except OneBotError:
        friends = []
    for friend in friends:
        if not isinstance(friend, dict) or not friend.get("user_id"):
            continue
        name = str(friend.get("remark") or friend.get("nickname") or "").strip()
        options.append({
            "type": "private",
            "id": str(friend["user_id"]),
            "name": name or str(friend["user_id"]),
        })

    try:
        groups = call(endpoint, access_token, "get_group_list").get("data") or []
    except OneBotError:
        groups = []
    for group in groups:
        if not isinstance(group, dict) or not group.get("group_id"):
            continue
        name = str(group.get("group_name") or "").strip()
        options.append({
            "type": "group",
            "id": str(group["group_id"]),
            "name": name or str(group["group_id"]),
        })

    return options


def deliver(
    endpoint: str,
    access_token: str,
    target_type: str,
    target_id: str,
    text: str,
) -> str:
    """Send one text message and return the message id."""
    kind = str(target_type or "").strip().lower()
    if kind == "group":
        action, key = "send_group_msg", "group_id"
    elif kind == "private":
        action, key = "send_private_msg", "user_id"
    else:
        raise OneBotError(f"不支持的接收类型：{target_type!r}（应为 private 或 group）")

    identifier = str(target_id or "").strip()
    if not identifier.isdigit():
        raise OneBotError(f"接收号码必须是纯数字：{target_id!r}")

    # OneBot v11 segments are {"type": ..., "data": {...}}. A flat {"type","text"}
    # segment is silently accepted by some implementations but rejected by NapCat
    # with retcode 200, so the nesting is not optional here.
    document = call(endpoint, access_token, action, {
        key: int(identifier),
        "message": [{"type": "text", "data": {"text": text}}],
    })
    message_id = (document.get("data") or {}).get("message_id")
    if message_id is None:
        raise OneBotError("OneBot 未返回 message_id，无法确认已发送")
    return str(message_id)
