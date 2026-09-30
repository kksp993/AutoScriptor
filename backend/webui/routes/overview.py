"""Dashboard projections: what the current account looks like right now."""
from __future__ import annotations

import time as _time

from fastapi import APIRouter, Request

from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.app_config import cfg
from ZmxyOL.character.profession import GAME_PROFESSIONS
from backend.webui.api_context import consume_runtime_config_updates
from backend.webui.api_response import api_error, api_ok
from orchestrator import current_version, orchestrator


router = APIRouter(tags=["overview"])


def _build_overview_payload(now_ts: float | None = None) -> dict:
    from orchestrator.model import (
        calc_effective_next_time,
        is_human_takeover_blocked,
        is_task_due,
        resolve_reschedule,
    )
    from tasks.task_register import task_registry

    now_ts = now_ts or _time.time()
    total = enabled = pending = scheduled = error = disabled = 0
    upcoming = []

    def _walk(task_table):
        """Count and list the current character's tasks; the table is flat and id-keyed."""
        nonlocal total, enabled, pending, scheduled, error, disabled
        for task_id, val in (task_table or {}).items():
            if not isinstance(val, dict) or 'on' not in val or 'next_exec_time' not in val:
                continue
            path = task_registry.get_path(task_id)
            if not path:
                continue
            total += 1
            if not val.get('on'):
                disabled += 1
                continue
            enabled += 1
            blocked = is_human_takeover_blocked(val, now_ts) or bool(val.get("error"))
            due = False if blocked else is_task_due(val, path, now_ts)
            if blocked:
                error += 1
            elif due:
                pending += 1
            else:
                scheduled += 1
            status = 'error' if blocked else ('pending' if due else 'scheduled')
            task_status = ((cfg._config.get("status") or {}).get("tasks") or {}).get(path, {})
            progress = task_status.get("progress") if isinstance(task_status, dict) else None
            progress_display = None
            if progress is not None:
                from tasks.task_state import progress_label

                progress_display = progress_label(progress) or str(progress)
            upcoming.append({
                'path': path,
                'on': True,
                'next_exec_time': calc_effective_next_time(val, now_ts, resolve_reschedule(path, val)),
                'status': status,
                'progress': progress,
                'progress_display': progress_display,
                'human_takeover_error': val.get('human_takeover_error'),
                'human_takeover_at': val.get('human_takeover_at'),
            })

    _walk(cfg._config.get('tasks', {}))
    order = {'pending': 0, 'error': 1, 'scheduled': 2}
    upcoming.sort(key=lambda x: (order.get(x['status'], 3), x['next_exec_time']))

    sched = orchestrator.scheduler.status_dict()
    sched['next_execution'] = orchestrator.scheduler.get_next_execution_timestamp()

    from AutoScriptor.core.runtime_context import runtime_ctx
    return {
        'scheduler': sched,
        'stats': {
            'total': total, 'enabled': enabled, 'pending': pending,
            'scheduled': scheduled, 'error': error, 'disabled': disabled,
        },
        'stats_all': orchestrator.tree.aggregate_stats_all_characters(now_ts),
        'overall_next_execution': orchestrator.tree.overall_next_execution_all_characters(),
        'upcoming': upcoming[:30],
        'runtime': runtime_ctx.status_dict(),
    }


@router.get("/api/overview")
async def overview_data_api():
    try:
        consume_runtime_config_updates()
        return _build_overview_payload()
    except Exception as e:
        logger.error("overview error: %s", e)
        return api_error(500, str(e), code="overview_failed")


@router.get("/api/runtime/snapshot")
async def runtime_snapshot_api(request: Request):
    try:
        consume_runtime_config_updates()
        now_ts = _time.time()
        overview = _build_overview_payload(now_ts)
        queue = orchestrator.tree.normalize_dispatch_queue(cfg._account_data.get("dispatch_queue", []))
        return api_ok(
            config_version=current_version(),
            credential={"unlocked": cfg.has_decrypted_credentials()},
            current_account=cfg.current_account(),
            accounts=cfg.list_accounts(),
            active_character=cfg.active_character(),
            character_name=cfg._config.get("game", {}).get("character_name", ""),
            characters=orchestrator.tree.characters_summary(),
            game_professions_by_character=orchestrator.tree.game_professions_by_character(),
            game_profession_options=list(GAME_PROFESSIONS),
            dispatch_queue=queue,
            all_tasks_summary=orchestrator.tree.all_characters_tasks_summary(),
            overview=overview,
            scheduler=overview["scheduler"],
            runtime=orchestrator.execution.status(),
        )
    except Exception as e:
        logger.error("runtime snapshot error: %s", e)
        return api_error(500, str(e), code="snapshot_failed")
