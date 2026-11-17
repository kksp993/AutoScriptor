"""Notification channel: the QQ / OneBot sink for per-character run results."""
from __future__ import annotations

import asyncio
import subprocess

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.core.qq_bot import local_installation_status, local_notification_settings
from backend.core.qq_login import LoginConflict, LoginOperationFailed, LoginUnavailable, local_qq_login
from backend.webui.api_context import guard_runtime_idle
from backend.webui.api_response import api_error, api_ok
from backend.webui.security import require_credential_unlock
from orchestrator import orchestrator
from orchestrator.delivery import CharacterReport, DeliveryError, qq_notifier


router = APIRouter(tags=["notifications"])



# ── QQ / OneBot ──


@router.get("/api/notify/qq")
def qq_get_settings():
    try:
        settings = orchestrator.tasks.prepare_qq_settings({})
    except ValueError as error:
        return api_error(400, str(error), code="invalid_notify_config")
    preview = CharacterReport(
        ("示例服务器", "示例角色"), 1,
        {"sample": ("每日任务/天庭/昆仑山", "success")},
    ).format_message()
    return api_ok(settings=settings.public_dict(), preview=preview, history=qq_notifier.history())


@router.post("/api/notify/qq")
async def qq_save_settings(request: Request):
    busy_response = guard_runtime_idle("save QQ notification settings")
    if busy_response is not None:
        return busy_response
    try:
        payload = await request.json()
        version = await asyncio.to_thread(orchestrator.tasks.save_qq_settings, payload)
    except ValueError as error:
        return api_error(400, str(error), code="invalid_notify_config")
    except OSError:
        return api_error(500, "QQ 配置写入失败，请检查文件权限后重试", code="notify_save_failed")
    return api_ok(config_version=version)


@router.post("/api/notify/qq/test")
async def qq_test_settings(request: Request):
    try:
        payload = await request.json()
        settings = await asyncio.to_thread(
            orchestrator.tasks.prepare_qq_settings, payload, require_target=True
        )
    except ValueError as error:
        return api_error(400, str(error), code="invalid_notify_config")
    record = await asyncio.to_thread(
        qq_notifier.deliver, settings,
        "AutoScriptor 测试通知\nQQ 结果通知已连接。这是测试消息，不代表真实任务执行。",
    )
    if not record["success"]:
        return api_error(502, record["error"], code="notify_delivery_failed")
    return api_ok(message="OneBot 已确认发送，请到 QQ 检查测试消息")


@router.get("/api/notify/qq/local")
def qq_get_local_bot():
    try:
        status = local_installation_status()
    except (OSError, ValueError):
        return api_error(500, "本机机器人安装文件缺失或配置损坏，请检查安装目录", code="local_bot_invalid")
    if status.get("installed"):
        # "Is the saved token still the right one?" is a question only this layer
        # can answer: the bot module deliberately does not read cfg, and the user
        # cannot compare two 64-character strings. Answering it here is what lets
        # the page say "nothing to do" instead of leaving a token box that implies
        # otherwise.
        try:
            saved = orchestrator.tasks.prepare_qq_settings({})
            connection = local_notification_settings()
            status["token_matches"] = bool(saved.access_token) and saved.access_token == connection["access_token"]
            status["endpoint_matches"] = saved.endpoint == connection["endpoint"]
        except (ValueError, OSError):
            # Unreadable or invalid stored settings; the page falls back to showing
            # the plain install status rather than claiming anything about the token.
            status["token_matches"] = False
            status["endpoint_matches"] = False
    return api_ok(**status)


@router.post("/api/notify/qq/local")
async def qq_use_local_bot():
    busy_response = guard_runtime_idle("use local QQ robot")
    if busy_response is not None:
        return busy_response
    try:
        connection = await asyncio.to_thread(local_notification_settings)
        version = await asyncio.to_thread(orchestrator.tasks.save_qq_settings, connection)
    except ValueError:
        return api_error(400, "本机机器人尚未完整安装，请运行 scripts\\install.bat qq", code="local_bot_invalid")
    except OSError:
        return api_error(500, "本机机器人配置读取或保存失败，请检查文件权限", code="notify_save_failed")
    return api_ok(config_version=version)


def _guard_local_login(request: Request):
    """Keep login capabilities on the local same-origin UI, even without a deploy password."""
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    client = request.client.host if request.client else ""
    origin = request.headers.get("origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if (
        client not in loopback_hosts
        or request.url.hostname not in loopback_hosts
        or request.headers.get("x-qq-login") != "1"
        or (origin is not None and origin != expected_origin)
        or request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none")
    ):
        return api_error(403, "请在运行机器的本地 AutoScriptor 页面管理机器人登录", code="local_login_only")
    return require_credential_unlock(request)


def _private_login_response(response):
    if isinstance(response, dict):
        response = JSONResponse(response)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/api/notify/qq/login")
async def qq_login_status(request: Request):
    blocked = _guard_local_login(request)
    if blocked is not None:
        return _private_login_response(blocked)
    try:
        status = await asyncio.to_thread(local_qq_login.status)
        return _private_login_response(api_ok(**status))
    except LoginUnavailable as error:
        return _private_login_response(api_error(503, str(error), code="qq_login_unavailable"))
    except (OSError, ValueError):
        return _private_login_response(api_error(503, "本机机器人配置或状态无效，无法确认登录", code="qq_login_invalid"))


@router.post("/api/notify/qq/login")
async def qq_login_action(request: Request):
    blocked = _guard_local_login(request) or guard_runtime_idle("change QQ robot login")
    if blocked is not None:
        return _private_login_response(blocked)
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) - {"action", "account", "confirm_switch", "_timestamp"}:
            raise ValueError("登录接口只接收操作、QQ 号和切换确认，不接收密码或令牌")
        response = await asyncio.to_thread(_perform_login_action, payload)
    except (LoginConflict, DeliveryError) as error:
        response = api_error(409, str(error), code="qq_login_conflict")
    except LoginOperationFailed as error:
        response = api_error(503, str(error), code=f"qq_login_{error.stage}_failed", stage=error.stage)
    except LoginUnavailable as error:
        response = api_error(503, str(error), code="qq_login_unavailable")
    except ValueError:
        response = api_error(400, "请求无效：请输入机器人 QQ 号；快捷登录需已有缓存。不要提交密码、令牌或 session。", code="qq_login_invalid")
    except (OSError, subprocess.SubprocessError):
        response = api_error(503, "机器人操作失败，请检查本机安装、权限和进程状态", code="qq_login_failed")
    return _private_login_response(response)


def _perform_login_action(payload: dict):
    with orchestrator.tasks.config_operation(), qq_notifier.login_operation():
        blocked = guard_runtime_idle("change QQ robot login")
        if blocked is not None:
            return blocked
        action = payload.get("action")
        if action in ("qr", "quick"):
            result = local_qq_login.start(
                payload.get("account", ""), action,
                confirm_switch=payload.get("confirm_switch") is True,
                on_starting=qq_notifier.require_login_confirmation,
            )
        elif action == "refresh_qr":
            result = local_qq_login.refresh_qr()
        elif action == "remember":
            result = local_qq_login.remember(payload.get("account", ""))
            qq_notifier.confirm_login()
        else:
            raise ValueError("不支持的机器人登录操作")
        return api_ok(**result)
