"""QQ notification settings; no dependency on the WebUI server singleton."""
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from services.core.character_reports import CharacterReport
from services.core.qq_bot import local_installation_status, local_notification_settings
from services.core.qq_notify import qq_notifier
from services.webui.api_response import api_error, api_ok


def create_notifications_router(lifecycle_service, guard_idle) -> APIRouter:
    router = APIRouter(prefix="/api/notify/qq", tags=["notifications"])

    @router.get("")
    def get_settings():
        try:
            settings = lifecycle_service.prepare_qq_settings({})
        except ValueError as error:
            return api_error(400, str(error), code="invalid_notify_config")
        preview = CharacterReport(
            ("示例服务器", "示例角色"), 1,
            {"sample": ("每日任务/天庭/昆仑山", "success")},
        ).format_message()
        return api_ok(settings=settings.public_dict(), preview=preview, history=qq_notifier.history())

    @router.post("")
    async def save_settings(request: Request):
        busy_response = guard_idle("save QQ notification settings")
        if busy_response is not None:
            return busy_response
        try:
            payload = await request.json()
            version = await run_in_threadpool(lifecycle_service.save_qq_settings, payload)
        except ValueError as error:
            return api_error(400, str(error), code="invalid_notify_config")
        except OSError:
            return api_error(500, "QQ 配置写入失败，请检查文件权限后重试", code="notify_save_failed")
        return api_ok(config_version=version)

    @router.post("/test")
    async def test_settings(request: Request):
        try:
            payload = await request.json()
            settings = await run_in_threadpool(
                lifecycle_service.prepare_qq_settings, payload, require_target=True
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

    @router.get("/local")
    def get_local_bot():
        try:
            return api_ok(**local_installation_status())
        except (OSError, ValueError):
            return api_error(500, "本机机器人安装文件缺失或配置损坏，请检查安装目录", code="local_bot_invalid")

    @router.post("/local")
    async def use_local_bot():
        busy_response = guard_idle("use local QQ robot")
        if busy_response is not None:
            return busy_response
        try:
            connection = await run_in_threadpool(local_notification_settings)
            version = await run_in_threadpool(lifecycle_service.save_qq_settings, connection)
        except ValueError:
            return api_error(400, "本机机器人尚未完整安装，请运行 scripts\\install.bat qq", code="local_bot_invalid")
        except OSError:
            return api_error(500, "本机机器人配置读取或保存失败，请检查文件权限", code="notify_save_failed")
        return api_ok(config_version=version)

    return router
