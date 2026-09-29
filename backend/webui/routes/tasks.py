"""Task configuration and execution control.

Every handler here delegates to the orchestrator lifecycle service; the HTTP
layer only validates input, guards against a running task and shapes the reply."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.app_config import cfg
from backend.webui.api_response import api_error, api_ok
from backend.webui.api_context import (
    busy_response,
    consume_runtime_config_updates,
    guard_runtime_idle,
    persistence_diagnostics,
    persistence_error_message,
    public_config_unlocked,
    task_ordering_response,
)
from backend.webui.security import (
    require_credential_unlock,
)
from orchestrator import RuntimeExecutionBusyError, SchedulerState, orchestrator


router = APIRouter(tags=["tasks"])

def _apply_run_character_from_body(body: dict, *, skip_character_login: bool = False):
    """
    若请求携带 server + character，在后端切换当前角色并写回 config/账号文件，
    默认使调度器下次执行前重新登录，避免前端已选角色与进程内 cfg 不一致。
    任务列表直跑会保留当前游戏登录状态，只切换任务配置投影。
    成功返回 None，失败返回 JSONResponse。
    """
    server = (body.get("server") or "").strip()
    character = (body.get("character") or "").strip()
    if not server or not character:
        return None
    try:
        orchestrator.tasks.switch_character(
            server,
            character,
            reason="select run character",
            invalidate_login=not skip_character_login,
        )
        logger.info("Selected role for execution: %s/%s", server, character)
    except (KeyError, ValueError) as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})
    except Exception as e:
        logger.error("run: switch character: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "切换角色失败"},
        )
    return None


@router.get("/api/refresh")
async def refresh_config_api():
    try:
        with orchestrator.tasks.config_operation():
            consume_runtime_config_updates()
            read_config()
            _apply_webui_log_level_from_config()
            return public_config_unlocked()
    except Exception as e:
        logger.error("refresh error: %s", e)
        return api_error(500, str(e), code="refresh_failed")


@router.post("/api/tasks/reload")
async def reload_tasks_api():
    busy = guard_runtime_idle("reload tasks")
    if busy is not None:
        return busy
    try:
        with orchestrator.tasks.config_operation():
            orchestrator.tasks.reload_task_state(reason="reload tasks")
            return public_config_unlocked()
    except Exception as e:
        logger.error("reload_tasks error: %s", e)
        return api_error(500, str(e), code="reload_tasks_failed")


@router.post("/api/config/sync")
async def sync_config_api(request: Request):
    busy = guard_runtime_idle("sync config")
    if busy is not None:
        return busy
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    security_key = data.get("security_key")
    try:
        version = orchestrator.tasks.sync_all_config(security_key, reason="sync config")
        return api_ok(status="ok", config_version=version)
    except Exception as e:
        logger.error("sync_config error: %s", e)
        return api_error(500, str(e), code="sync_config_failed")


@router.post("/api/tasks/reload-all")
async def reload_all_tasks_api():
    busy = guard_runtime_idle("reload all tasks")
    if busy is not None:
        return busy
    try:
        with orchestrator.tasks.config_operation():
            orchestrator.tasks.reload_all(reason="reload all")
            return public_config_unlocked()
    except Exception as e:
        logger.error("reload_all_tasks error: %s", e)
        return api_error(500, str(e), code="reload_all_tasks_failed")


@router.post("/api/config")
async def save_config_api(request: Request):
    busy = guard_runtime_idle("save config")
    if busy is not None:
        return busy
    data = await request.json()
    if not isinstance(data, dict):
        return api_error(400, "invalid config payload", code="invalid_payload")
    try:
        return api_ok(config_version=orchestrator.tasks.save_runtime_config(data))
    except (KeyError, ValueError) as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("save config error: %s", e)
        return api_error(
            500,
            persistence_error_message("保存配置失败", e),
            code="save_config_failed",
            diagnostics=persistence_diagnostics(),
        )


@router.post("/api/tasks")
async def save_tasks_api(request: Request):
    busy = guard_runtime_idle("save tasks")
    if busy is not None:
        return busy
    try:
        payload = await request.json()
        tasks = payload.get('tasks', payload)
        if not isinstance(tasks, dict):
            return api_error(400, "invalid tasks payload", code="invalid_payload")
        with orchestrator.tasks.config_operation():
            orchestrator.tasks.save_tasks(tasks)
            return public_config_unlocked()
    except Exception as e:
        logger.error("save_tasks error: %s", e)
        return api_error(
            500,
            persistence_error_message("保存任务失败", e),
            code="save_tasks_failed",
            diagnostics=persistence_diagnostics(),
        )


@router.get("/api/task-ordering")
async def task_ordering_api():
    try:
        with orchestrator.tasks.config_operation():
            return task_ordering_response()
    except Exception as e:
        logger.error("task_ordering read error: %s", e, exc_info=True)
        return api_error(500, str(e), code="task_ordering_read_failed")


@router.post("/api/task-ordering")
async def save_task_ordering_api(request: Request):
    busy = guard_runtime_idle("save task ordering")
    if busy is not None:
        return busy
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return api_error(400, "invalid task ordering payload", code="invalid_payload")
        raw_overlay = payload.get("overlay", payload)
        with orchestrator.tasks.config_operation():
            orchestrator.tasks.save_task_ordering(raw_overlay)
            return task_ordering_response()
    except ValueError as e:
        return api_error(400, str(e), code="invalid_task_ordering")
    except Exception as e:
        logger.error("save_task_ordering error: %s", e, exc_info=True)
        return api_error(
            500,
            persistence_error_message("保存任务排序失败", e),
            code="save_task_ordering_failed",
            diagnostics=persistence_diagnostics(),
        )


@router.post("/api/task-ordering/layout")
async def save_task_ordering_layout_api(request: Request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return api_error(400, "invalid task ordering layout payload", code="invalid_payload")
        raw_layout = payload.get("layout", payload)
        config_version = orchestrator.tasks.save_task_ordering_layout(raw_layout)
        projection = orchestrator.tree.task_ordering_projection()
        return api_ok(
            status="ok",
            config_version=config_version,
            projection=projection.to_public_dict(),
        )
    except ValueError as e:
        return api_error(400, str(e), code="invalid_task_ordering_layout")
    except Exception as e:
        logger.error("save_task_ordering_layout error: %s", e, exc_info=True)
        return api_error(
            500,
            persistence_error_message("保存任务图布局失败", e),
            code="save_task_ordering_layout_failed",
            diagnostics=persistence_diagnostics(),
        )


@router.post("/api/run")
async def run_tasks_api(request: Request):
    raw = await request.json()
    if isinstance(raw, list):
        body = {"tasks": raw, "activate_scheduler": True}
    elif isinstance(raw, dict):
        body = raw
    else:
        body = {}

    err = require_credential_unlock(request)
    if err is not None:
        return err

    activate_sched = bool(body.get("activate_scheduler", True))
    execution_source = str(body.get("execution_source") or "").strip()
    skip_character_login = not activate_sched and execution_source == "task_list"
    direct_busy = orchestrator.execution.direct_run_alive()
    if activate_sched:
        if orchestrator.execution.is_busy():
            return busy_response("start scheduler")
        if orchestrator.scheduler.state == SchedulerState.ERROR:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "error",
                    "message": "调度器处于错误状态，请先恢复调度后再启动",
                },
            )
        if not orchestrator.tree.normalize_dispatch_queue(cfg._account_data.get("dispatch_queue", [])):
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "调度队列为空，请先添加要参与调度的角色",
                },
            )
    elif orchestrator.execution.is_busy():
        return busy_response("run task")

    err = _apply_run_character_from_body(body, skip_character_login=skip_character_login)
    if err is not None:
        return err

    character_name = cfg._config.get("game", {}).get("character_name", "")
    if not character_name:
        return JSONResponse(status_code=403,
                            content={'status': 'error', 'message': '请先验证账号密码后再执行任务'})

    tasks = body.get("tasks", [])
    logger.debug(
        "Received tasks: %s, activate_scheduler: %s, execution_source: %s",
        tasks,
        activate_sched,
        execution_source or "default",
    )
    sorted_tasks = orchestrator.tree.sort_task_paths(tasks)

    if activate_sched:
        if direct_busy:
            return api_error(
                409,
                "单任务或队列正在直接执行中，请先终止后再启动调度",
                code="runtime_busy",
                reason="direct_run",
            )
        orchestrator.scheduler.activate()
        orchestrator.scheduler.wake()
        return api_ok(status='ok', tasks=sorted_tasks, mode='scheduler')

    if direct_busy:
        return api_error(
            409,
            "已有任务正在执行，请先终止后再试",
            code="runtime_busy",
            reason="direct_run",
        )
    def _run(ts):
        orchestrator.scheduler.run_direct(ts, skip_character_login=skip_character_login)
        logger.info("========== 所有任务执行完成 ==========")

    try:
        orchestrator.execution.start_direct(_run, sorted_tasks)
    except RuntimeExecutionBusyError:
        return busy_response("run task")
    return api_ok(status='ok', tasks=sorted_tasks, mode='direct')


@router.get("/api/run/status")
async def run_status_api():
    """轻量运行状态接口；统一前端状态以 /api/runtime/snapshot 为准。"""
    return {"running": orchestrator.execution.direct_run_alive(), "runtime": orchestrator.execution.status()}


@router.post("/api/stop")
async def stop_tasks_api():
    try:
        return api_ok(status=orchestrator.execution.request_stop(), runtime=orchestrator.execution.status())
    except Exception as e:
        logger.error("stop error: %s", e)
        return api_error(500, str(e), code="stop_failed")


@router.get("/api/scheduler/status")
async def scheduler_status_api():
    return orchestrator.scheduler.status_dict()


@router.post("/api/scheduler/reset")
async def scheduler_reset_api():
    busy = guard_runtime_idle("reset scheduler")
    if busy is not None:
        return busy
    orchestrator.scheduler.reset()
    return orchestrator.scheduler.status_dict()


@router.post("/api/scheduler/deactivate")
async def scheduler_deactivate_api():
    """仅将调度器切回待运行，不取消直接执行线程、不发送 cancel。"""
    orchestrator.scheduler.deactivate()
    return orchestrator.scheduler.status_dict()
