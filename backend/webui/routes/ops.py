"""Machine-level operations: the emulator and OCR probe, source updates, remote
access, deployment settings, config import/export and error archives.

None of this touches game state, which is why it is one module."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.app_config import cfg
from backend.webui.api_response import api_error, api_ok
from backend.webui.api_context import (
    guard_runtime_idle,
    public_config,
)
from orchestrator import orchestrator


router = APIRouter(tags=["ops"])


@router.get("/api/update/status")
async def update_status_api():
    from backend.core.updater import updater
    return updater.get_status()


@router.post("/api/update/check")
async def update_check_api():
    from backend.core.updater import updater
    has_update = updater.check_update()
    return {"has_update": has_update, **updater.get_status()}


@router.post("/api/update/run")
async def update_run_api():
    busy = guard_runtime_idle("run source update")
    if busy is not None:
        return busy
    from backend.core.updater import updater
    ok = updater.run_update()
    return {"success": ok, **updater.get_status()}


@router.get("/api/remote-access")
async def remote_access_status_api():
    from backend.core.remote_access import RemoteAccess
    return RemoteAccess.get_status()


@router.post("/api/remote-access")
async def remote_access_toggle_api(request: Request):
    data = await request.json()
    from backend.core.remote_access import RemoteAccess
    if data.get("enabled"):
        if not cfg._config.get("deploy", {}).get("password"):
            return api_error(
                403,
                "开启远程访问前请先设置 WebUI 访问密码",
                code="deploy_password_required",
            )
        RemoteAccess.start(
            local_port=5000,
            ssh_server=cfg.get("remote_access.ssh_server", ""),
            ssh_user=cfg.get("remote_access.ssh_user", ""),
            ssh_executable=cfg.get("remote_access.ssh_executable", "ssh"),
        )
    else:
        RemoteAccess.stop()
    return RemoteAccess.get_status()


@router.get("/api/deploy")
async def deploy_get_api():
    deploy_copy = dict(cfg._config.get("deploy", {}))
    has_pwd = bool(deploy_copy.get("password"))
    deploy_copy["password"] = ""
    notify_copy = dict(cfg._config.get("notify", {}))
    notify_copy.pop("qq", None)
    return {
        "deploy": deploy_copy,
        "password_protected": has_pwd,
        "notify": notify_copy,
        "update": cfg._config.get("update", {}),
        "remote_access": cfg._config.get("remote_access", {}),
    }


@router.post("/api/deploy")
async def deploy_save_api(request: Request):
    busy = guard_runtime_idle("save deploy settings")
    if busy is not None:
        return busy
    data = await request.json()
    for section in ("deploy", "notify", "update", "remote_access"):
        if section in data:
            if section == "deploy":
                incoming = data["deploy"]
                incoming_pwd = incoming.get("password")
                existing_pwd = cfg._config.get("deploy", {}).get("password")
                current_pwd = incoming.pop("current_password", None)

                if incoming_pwd is None and existing_pwd:
                    if not current_pwd or not _verify_deploy_password(current_pwd, existing_pwd):
                        return JSONResponse(status_code=403, content={"error": "清除密码需要验证当前密码"})
                    incoming["password"] = None
                elif incoming_pwd == "":
                    incoming["password"] = existing_pwd
                elif incoming_pwd:
                    if existing_pwd:
                        if not current_pwd or not _verify_deploy_password(current_pwd, existing_pwd):
                            return JSONResponse(status_code=403, content={"error": "修改密码需要验证当前密码"})
                    incoming["password"] = _hash_deploy_password(incoming_pwd)
    return api_ok(status="ok", config_version=orchestrator.tasks.save_deploy_sections(data))


@router.get("/api/config/export")
async def config_export_api():
    from fastapi.responses import Response
    safe = public_config()
    content = json.dumps(safe, ensure_ascii=False, indent=4)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=autoscriptor-config.json"},
    )


@router.post("/api/config/import")
async def config_import_api(request: Request):
    busy = guard_runtime_idle("import config")
    if busy is not None:
        return busy
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(status_code=400, content={"error": "invalid JSON"})
        version = orchestrator.tasks.import_config(data)
        return api_ok(status="ok", config_version=version)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/api/error-archives")
async def error_archives_list_api():
    try:
        return list_error_archives()
    except Exception as e:
        logger.exception("error-archives list failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/api/error-archives/detail")
async def error_archives_detail_api(folder: str):
    try:
        detail = get_archive_detail(folder)
        if not detail:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return detail
    except Exception as e:
        logger.exception("error-archives detail failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/api/error-archives/file")
async def error_archives_file_api(folder: str, path: str):
    try:
        p = read_archive_file(folder, path)
        if not p:
            return JSONResponse(status_code=404, content={"error": "not found"})
        suffix = p.suffix.lower()
        media = "image/png" if suffix == ".png" else "image/jpeg" if suffix in (".jpg", ".jpeg") else "video/mp4" if suffix == ".mp4" else "application/octet-stream"
        return FileResponse(p, media_type=media, filename=p.name)
    except Exception as e:
        logger.exception("error-archives file failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.delete("/api/error-archives")
async def error_archives_delete_api(request: Request):
    try:
        data = await request.json()
        folders = data.get("folders") or []
        if not isinstance(folders, list):
            return JSONResponse(status_code=400, content={"error": "folders must be a list"})
        return delete_archives([str(x) for x in folders])
    except Exception as e:
        logger.exception("error-archives delete failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/api/error-archives/import")
async def error_archives_import_api(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        if not raw:
            return JSONResponse(status_code=400, content={"error": "empty file"})
        name = (file.filename or "import").rsplit(".", 1)[0]
        result = import_zip_bytes(raw, suggested_name=name)
        if not result.get("ok"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        logger.exception("error-archives import failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/api/ocr-status")
async def ocr_status_api():
    try:
        import paddle
        from AutoScriptor.recognition.ocr_rec import get_ocr_runtime_status

        runtime_status = get_ocr_runtime_status()
        compiled_with_cuda = paddle.device.is_compiled_with_cuda()
        gpu_count = paddle.device.cuda.device_count()
        current_device = paddle.get_device()
        return {
            "paddle_version": paddle.__version__,
            "cfg_use_gpu": runtime_status["configured_use_gpu"],
            "configured_use_gpu": runtime_status["configured_use_gpu"],
            "runtime_use_gpu": runtime_status["runtime_use_gpu"],
            "engine_use_gpu": runtime_status["engine_use_gpu"],
            "compiled_with_cuda": compiled_with_cuda,
            "gpu_count": gpu_count,
            "current_device": current_device,
            "engine_device": runtime_status["engine_device"],
            "engine_ready": runtime_status["engine_ready"],
            "restart_required": runtime_status["restart_required"],
            "initialization_error": runtime_status["initialization_error"],
            "configured_model": runtime_status["configured_model"],
            "runtime_model": runtime_status["runtime_model"],
        }
    except Exception as e:
        logger.error("ocr_status error: %s", e)
        return api_error(500, str(e), code="ocr_status_failed")


@router.get("/api/device/diagnostics")
async def device_diagnostics_api(screenshot: bool = False, require_app: bool = False):
    try:
        diagnostics = get_device_facade().diagnostics(
            include_screenshot=screenshot,
            require_app=require_app,
        )
        diagnostics["discovery"] = discover_mumu_setup(cfg["emulator"], probe_adb=False)
        return api_ok(diagnostics=diagnostics)
    except Exception as e:
        logger.error("device diagnostics error: %s", e)
        return api_error(500, str(e), code="device_diagnostics_failed")


@router.get("/api/device/discover")
async def device_discover_api(probe_adb: bool = True):
    try:
        return api_ok(discovery=discover_mumu_setup(cfg["emulator"], probe_adb=probe_adb))
    except Exception as e:
        logger.error("device discovery error: %s", e)
        return api_error(500, str(e), code="device_discovery_failed")


@router.post("/api/device/discover/apply")
async def device_discover_apply_api(request: Request):
    busy = guard_runtime_idle("apply device discovery")
    if busy is not None:
        return busy
    try:
        data = await request.json()
        emulator = data.get("emulator", data) if isinstance(data, dict) else {}
        version = orchestrator.tasks.apply_discovered_emulator_config(emulator)
        return api_ok(config_version=version, discovery=discover_mumu_setup(cfg["emulator"], probe_adb=False))
    except (KeyError, ValueError) as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("device discovery apply error: %s", e)
        return api_error(500, str(e), code="device_discovery_apply_failed")
