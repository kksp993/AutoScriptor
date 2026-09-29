"""Notification channels: the onepush YAML sink and the QQ / OneBot sink.

One module because the settings page configures "where results get sent" as a
whole; the two channels differ in transport, not in what the caller wants.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from backend.core.qq_bot import local_installation_status, local_notification_settings
from backend.webui.api_context import guard_runtime_idle
from backend.webui.api_response import api_error, api_ok
from orchestrator import orchestrator
from orchestrator.delivery import CharacterReport, handle_notify, qq_notifier


router = APIRouter(tags=["notifications"])


# ── 通用推送（onepush YAML）──


@router.post("/api/notify/test")
async def notify_test(request: Request):
    data = await request.json()
    config_yaml = data.get("config_yaml", "") if isinstance(data, dict) else ""
    delivered = await run_in_threadpool(
        handle_notify, config_yaml,
        title="AutoScriptor 测试",
        content="通知推送测试成功",
    )
    if not delivered:
        return api_error(502, "推送未成功，请检查 provider 配置", code="notify_delivery_failed")
    return api_ok(message="推送已发送")


@router.post("/api/notify/save")
async def notify_save(request: Request):
    busy_response = guard_runtime_idle("save notify settings")
    if busy_response is not None:
        return busy_response
    data = await request.json()
    version = await run_in_threadpool(
        orchestrator.tasks.save_notify_settings,
        data.get("enabled", False),
        data.get("config_yaml", "provider: null"),
    )
    return api_ok(status="ok", config_version=version)


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
        version = await run_in_threadpool(orchestrator.tasks.save_qq_settings, payload)
    except ValueError as error:
        return api_error(400, str(error), code="invalid_notify_config")
    except OSError:
        return api_error(500, "QQ 配置写入失败，请检查文件权限后重试", code="notify_save_failed")
    return api_ok(config_version=version)


@router.post("/api/notify/qq/test")
async def qq_test_settings(request: Request):
    try:
        payload = await request.json()
        settings = await run_in_threadpool(
            orchestrator.tasks.prepare_qq_settings, payload, require_target=True
        )
    except ValueError as error:
        return api_error(400, str(error), code="invalid_notify_config")
    record = await run_in_threadpool(
        qq_notifier.deliver, settings,
        "AutoScriptor 测试通知\nQQ 结果通知已连接。这是测试消息，不代表真实任务执行。",
    )
    if not record["success"]:
        return api_error(502, record["error"], code="notify_delivery_failed")
    return api_ok(message="OneBot 已确认发送，请到 QQ 检查测试消息")


@router.get("/api/notify/qq/local")
def qq_get_local_bot():
    try:
        return api_ok(**local_installation_status())
    except (OSError, ValueError):
        return api_error(500, "本机机器人安装文件缺失或配置损坏，请检查安装目录", code="local_bot_invalid")


@router.post("/api/notify/qq/local")
async def qq_use_local_bot():
    busy_response = guard_runtime_idle("use local QQ robot")
    if busy_response is not None:
        return busy_response
    try:
        connection = await run_in_threadpool(local_notification_settings)
        version = await run_in_threadpool(orchestrator.tasks.save_qq_settings, connection)
    except ValueError:
        return api_error(400, "本机机器人尚未完整安装，请运行 scripts\\install.bat qq", code="local_bot_invalid")
    except OSError:
        return api_error(500, "本机机器人配置读取或保存失败，请检查文件权限", code="notify_save_failed")
    return api_ok(config_version=version)
