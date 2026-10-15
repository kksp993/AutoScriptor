"""Accounts, characters, the dispatch queue and the credential unlock."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.core import qq_bot
from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.app_config import cfg
from backend.webui.api_response import api_error, api_ok
from backend.webui.api_context import (
    guard_runtime_idle,
    mark_config_changed,
    persistence_diagnostics,
    persistence_error_message,
    public_config,
)
from backend.webui.security import (
    attach_credential_unlock_cookie,
    check_request_freshness,
    clear_credential_unlock_cookie,
    credential_unlock_from_request,
    grant_credential_unlock,
    is_verify_rate_limited,
    record_verify_failure,
    revoke_credential_unlock,
    validate_credential_unlock,
)
from orchestrator import current_version, orchestrator


router = APIRouter(tags=["accounts"])


@router.get("/api/accounts")
async def accounts_list_api():
    return {
        "current_account": cfg.current_account(),
        "accounts": cfg.list_accounts(),
        "active_character": cfg.active_character(),
        "characters": orchestrator.tree.characters_summary(),
    }


@router.post("/api/accounts/switch")
async def accounts_switch_api(request: Request):
    busy = guard_runtime_idle("switch account")
    if busy is not None:
        return busy
    data = await request.json()
    if not check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    name = data.get("name", "")
    security_key = data.get("security_key", "")
    client_ip = request.client.host if request.client else "unknown"

    if not security_key:
        return JSONResponse(status_code=400, content={
            "error": "请输入安全密码以切换账号", "need_security_key": True,
        })
    if not cfg.verify_account_security_key(name, security_key):
        record_verify_failure(client_ip)
        return JSONResponse(status_code=401, content={"error": "安全密码错误"})
    try:
        version = orchestrator.tasks.switch_account(name, security_key)
        character_name = cfg._config.get("game", {}).get("character_name", "")
        ac = cfg.active_character()
        old_tok = credential_unlock_from_request(request)
        revoke_credential_unlock(old_tok)
        tok = grant_credential_unlock()
        resp = JSONResponse(
            content={
                "current_account": name,
                "character_name": character_name,
                "active_character": ac,
                "characters": orchestrator.tree.characters_summary(),
                "config_version": version,
            }
        )
        return attach_credential_unlock_cookie(resp, tok)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        logger.error("switch account error: %s", e)
        return JSONResponse(status_code=500, content={"error": "切换失败，请检查安全密码是否正确"})


@router.post("/api/accounts/add")
async def accounts_add_api(request: Request):
    busy = guard_runtime_idle("add account")
    if busy is not None:
        return busy
    data = await request.json()
    if not check_request_freshness(data):
        return api_error(400, "请求已过期，请重试", code="stale_request")
    name = str(data.get("name", "") or "").strip()
    account = str(data.get("account", "") or "").strip()
    password = str(data.get("password", "") or "").strip()
    server = str(data.get("server", "") or "").strip()
    character_name = str(data.get("character_name", "") or "").strip()
    security_key = str(data.get("security_key", "") or "").strip()

    if not name:
        return api_error(400, "账号名称不能为空", code="invalid_payload")
    if not account:
        return api_error(400, "游戏账号不能为空", code="invalid_payload")
    if not password:
        return api_error(400, "游戏密码不能为空", code="invalid_payload")
    if not server:
        return api_error(400, "服务器不能为空", code="invalid_payload")
    if not character_name:
        return api_error(400, "角色名不能为空", code="invalid_payload")
    if not security_key:
        return api_error(400, "安全密码不能为空", code="invalid_payload")

    try:
        version = orchestrator.tasks.add_account(name, account, password, server, character_name, security_key)
        old_tok = credential_unlock_from_request(request)
        revoke_credential_unlock(old_tok)
        tok = grant_credential_unlock()
        resp = JSONResponse(content=api_ok(
            accounts=cfg.list_accounts(),
            current_account=cfg.current_account(),
            character_name=cfg._config.get("game", {}).get("character_name", ""),
            active_character=cfg.active_character(),
            characters=orchestrator.tree.characters_summary(),
            credential={"unlocked": cfg.has_decrypted_credentials()},
            config_version=version,
        ))
        return attach_credential_unlock_cookie(resp, tok)
    except ValueError as e:
        return api_error(400, str(e), code="invalid_account")
    except Exception as e:
        logger.error("add account error: %s", e)
        return api_error(
            500,
            persistence_error_message("创建账号失败", e),
            code="add_account_failed",
            diagnostics=persistence_diagnostics(),
        )


@router.post("/api/accounts/delete")
async def accounts_delete_api(request: Request):
    busy = guard_runtime_idle("delete account")
    if busy is not None:
        return busy
    data = await request.json()
    name = data.get("name", "")
    try:
        version = orchestrator.tasks.delete_account(name)
        return {
            "accounts": cfg.list_accounts(),
            "current_account": cfg.current_account(),
            "config_version": version,
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.get("/api/characters")
async def characters_list_api():
    return {
        "active_character": cfg.active_character(),
        "characters": orchestrator.tree.characters_summary(),
    }


@router.post("/api/characters/switch")
async def characters_switch_api(request: Request):
    busy = guard_runtime_idle("switch character")
    if busy is not None:
        return busy
    data = await request.json()
    if not check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        version = orchestrator.tasks.switch_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "character_name": character,
            "characters": orchestrator.tree.characters_summary(),
            "config_version": version,
        }
    except (KeyError, ValueError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        logger.error("switch character error: %s", e)
        return JSONResponse(status_code=500, content={"error": "切换角色失败"})


@router.post("/api/characters/add")
async def characters_add_api(request: Request):
    busy = guard_runtime_idle("add character")
    if busy is not None:
        return busy
    data = await request.json()
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        version = orchestrator.tasks.add_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "characters": orchestrator.tree.characters_summary(),
            "config_version": version,
        }
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.post("/api/characters/delete")
async def characters_delete_api(request: Request):
    busy = guard_runtime_idle("delete character")
    if busy is not None:
        return busy
    data = await request.json()
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        version = orchestrator.tasks.delete_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "characters": orchestrator.tree.characters_summary(),
            "config_version": version,
        }
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.post("/api/characters/game_profession")
async def characters_game_profession_api(request: Request):
    busy = guard_runtime_idle("change character profession")
    if busy is not None:
        return busy
    """写入指定角色的游戏职业（存账号 JSON），当前角色同步 cfg.game。"""
    data = await request.json()
    if not check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    server = (data.get("server") or "").strip()
    character = (data.get("character") or "").strip()
    profession = (data.get("game_profession") or "").strip()
    try:
        version = orchestrator.tasks.set_character_profession(server, character, profession)
        return {
            "game_professions_by_character": orchestrator.tree.game_professions_by_character(),
            "game": {"game_profession": cfg._config.get("game", {}).get("game_profession", "")},
            "config_version": version,
        }
    except (KeyError, ValueError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        logger.error("game_profession error: %s", e)
        return JSONResponse(status_code=500, content={"error": "保存职业失败"})


@router.get("/api/characters/all_tasks_summary")
async def characters_all_tasks_summary_api():
    try:
        return {"characters": orchestrator.tree.all_characters_tasks_summary()}
    except Exception as e:
        logger.error("all_tasks_summary error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/api/characters/task")
async def get_character_task_api(server: str, character: str, path: str):
    try:
        node = orchestrator.tree.get_character_task_public(server, character, path)
        if not node:
            return api_error(404, "task not found", code="task_not_found")
        return api_ok(task=node, path=path, server=server, character=character)
    except Exception as e:
        logger.error("get_character_task error: %s", e)
        return api_error(500, str(e), code="get_character_task_failed")


@router.post("/api/characters/task")
async def save_character_task_api(request: Request):
    busy = guard_runtime_idle("save character task")
    if busy is not None:
        return busy
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return api_error(400, "invalid payload", code="invalid_payload")
        server = (body.get("server") or "").strip()
        character = (body.get("character") or "").strip()
        path = (body.get("path") or "").strip()
        task = body.get("task")
        if not server or not character or not path or not isinstance(task, dict):
            return api_error(400, "invalid character task payload", code="invalid_payload")
        orchestrator.tasks.save_character_task(server, character, path, task)
        ac = cfg.active_character()
        if ac.get("server") == server and ac.get("name") == character:
            return public_config()
        version = current_version()
        return api_ok(config_version=version)
    except (KeyError, ValueError) as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("save_character_task error: %s", e)
        return api_error(
            500,
            persistence_error_message("保存任务失败", e),
            code="save_character_task_failed",
            diagnostics=persistence_diagnostics(),
        )


@router.get("/api/dispatch/queue")
async def dispatch_queue_get_api():
    queue = orchestrator.tree.normalize_dispatch_queue(cfg._account_data.get("dispatch_queue", []))
    return {"queue": queue}


@router.post("/api/dispatch/queue")
async def dispatch_queue_save_api(request: Request):
    busy = guard_runtime_idle("save dispatch queue")
    if busy is not None:
        return busy
    data = await request.json()
    queue, version = orchestrator.tasks.save_dispatch_queue(data.get("queue", []))
    return {"queue": queue, "config_version": version}


@router.get("/api/credential/status")
async def credential_status_api(request: Request):
    """前端同步「是否可执行」：仅看 cfg 中是否已有已解密账密。"""
    return {"unlocked": cfg.has_decrypted_credentials()}


@router.post("/api/credential/revoke")
async def credential_revoke_api(request: Request):
    """用户主动「重新验证」时吊销解锁令牌并清除 Cookie。"""
    busy = guard_runtime_idle("revoke credentials")
    if busy is not None:
        return busy
    old = credential_unlock_from_request(request)
    revoke_credential_unlock(old)
    cfg.clear_decrypted_credentials()
    resp = JSONResponse(content={"status": "ok"})
    return clear_credential_unlock_cookie(resp)


@router.post("/api/verify")
async def verify_account_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if is_verify_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "验证尝试过多，请5分钟后再试"})

    busy = guard_runtime_idle("verify account")
    if busy is not None:
        return busy

    data = await request.json()
    if not check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    security_key = data.get("security_key", "")
    has_enc = cfg.has_encrypted_credentials()
    if has_enc and not str(security_key).strip():
        return JSONResponse(status_code=401, content={"error": "请输入安全密码"})

    try:
        character_name = orchestrator.tasks.reload_verified_account(security_key)
    except Exception as e:
        logger.error("verify reload_tasks: %s", e)
        return JSONResponse(status_code=500, content={"error": "加载配置失败"})

    if has_enc:
        if not cfg.has_decrypted_credentials():
            record_verify_failure(client_ip)
            return JSONResponse(status_code=401, content={"error": "安全密码错误"})

    if not character_name:
        return JSONResponse(
            status_code=400,
            content={"error": "账号中未找到角色，请先选择或创建角色"},
        )

    if cfg.get("notify.qq.enabled", False):
        try:
            await asyncio.to_thread(qq_bot.ensure_bot_running)
        except (OSError, ValueError) as error:
            logger.warning("安全密码验证后自动启动 QQ 机器人失败: %s", error)

    old_tok = credential_unlock_from_request(request)
    revoke_credential_unlock(old_tok)
    tok = grant_credential_unlock()
    version = mark_config_changed("verify account")
    resp = JSONResponse(
        content={
            "character_name": character_name,
            "active_character": cfg.active_character(),
            "config_version": version,
        }
    )
    return attach_credential_unlock_cookie(resp, tok)


@router.post("/api/account")
async def update_account_credentials_api(request: Request):
    """Update the encryption (account/password) for the current account."""
    busy = guard_runtime_idle("update account credentials")
    if busy is not None:
        return busy
    data = await request.json()
    if not check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})

    client_ip = request.client.host if request.client else "unknown"
    if is_verify_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "操作过于频繁，请5分钟后再试"})

    account = data.get('account', '')
    password = data.get('password', '')
    security_key = data.get('security_key', '')
    confirmed = data.get('confirmed', False)
    current_security_key = data.get('current_security_key', '')
    unlocked = validate_credential_unlock(credential_unlock_from_request(request))

    if cfg.has_encrypted_credentials():
        if not unlocked and not current_security_key:
            return JSONResponse(status_code=403, content={
                "error": "修改账密需要先验证当前安全密码",
                "need_current_key": True,
            })
        if not unlocked:
            if not cfg.verify_account_security_key(cfg.current_account(), current_security_key):
                record_verify_failure(client_ip)
                return JSONResponse(status_code=401, content={"error": "当前安全密码验证失败"})
       

    # 只有真的存在加密凭据时才谈「覆盖」：新账号本来就没有凭据，拿角色名当理由
    # 会让第一次填账密的用户看到一句「会覆盖当前已有的加密设置」而不敢继续。
    existing_name = cfg._config.get("game", {}).get("character_name", "")
    if cfg.has_encrypted_credentials() and not confirmed:
        return {
            "need_confirm": True,
            "message": f"更新账密会覆盖当前已有的加密设置（当前角色: {existing_name}），是否继续？"
        }
    try:
        character_name, version = orchestrator.tasks.update_account_credentials(account, password, security_key)
    except Exception as e:
        logger.error("update_account error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    old_tok = credential_unlock_from_request(request)
    revoke_credential_unlock(old_tok)
    tok = grant_credential_unlock()
    resp = JSONResponse(content={"character_name": character_name, "config_version": version})
    return attach_credential_unlock_cookie(resp, tok)
