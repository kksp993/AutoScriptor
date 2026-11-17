"""Thin platform binding for the persistent AutoScriptor CLI flow service."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from AutoScriptor.cli import AutomationService, ExecutionBusyError, capabilities, parse_script, transform_with_map
from backend.webui.api_response import api_error, api_ok


def create_router(service: AutomationService, *, require_unlock, identity, execution_ready=lambda: True):
    router = APIRouter(prefix='/api/ascli', tags=['ascli'])

    async def read_payload(request):
        raw = await request.body()
        if len(raw) > 256 * 1024:
            raise ValueError('Request body exceeds 256 KiB')
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError('Expected a JSON object')
        return payload

    def failure(error):
        if isinstance(error, ExecutionBusyError):
            return api_error(409, str(error), code='runtime_busy')
        if isinstance(error, FileNotFoundError):
            return api_error(404, 'Run or artifact not found', code='ascli_not_found')
        if isinstance(error, (ValueError, TypeError, KeyError)):
            return api_error(400, str(error), code='invalid_ascli_request')
        return api_error(500, str(error), code='ascli_failed')

    @router.get('/capabilities')
    async def get_capabilities():
        return api_ok(version=1, commands=capabilities())

    @router.get('/status')
    async def status():
        return api_ok(**service.status())

    @router.post('/check')
    async def check(request: Request):
        try:
            payload = await read_payload(request)
            plan = parse_script(payload.get('source'))
            return api_ok(commands=len(plan.commands), requires_unsafe=plan.requires_unsafe, device_actions_executed=False)
        except Exception as error:
            return failure(error)

    @router.post('/transform')
    async def transform(request: Request):
        try:
            payload = await read_payload(request)
            code, line_map = transform_with_map(payload.get('source'))
            return api_ok(code=code, source_map=line_map, device_actions_executed=False)
        except Exception as error:
            return failure(error)

    @router.post('/runs')
    async def submit(request: Request):
        if not execution_ready():
            return api_error(503, 'Backend initialization has not completed successfully', code='runtime_not_ready')
        locked = require_unlock(request)
        if locked is not None:
            return locked
        try:
            payload = await read_payload(request)
            unknown = set(payload) - {'source', 'timeout', 'request_id', 'allow_unsafe'}
            if unknown:
                raise ValueError(f'Unknown fields: {sorted(unknown)}')
            return api_ok(**service.submit(identity=identity(), **payload))
        except Exception as error:
            return failure(error)

    @router.get('/runs/{run_id}')
    async def get_run(run_id: str):
        try:
            return api_ok(**service.get_run(run_id))
        except Exception as error:
            return failure(error)

    @router.post('/runs/{run_id}/stop')
    async def stop(run_id: str):
        try:
            return api_ok(**service.stop(run_id))
        except Exception as error:
            return failure(error)

    @router.get('/runs/{run_id}/artifacts')
    async def artifacts(run_id: str):
        try:
            return api_ok(**service.artifacts(run_id))
        except Exception as error:
            return failure(error)

    @router.get('/runs/{run_id}/logs')
    async def logs(run_id: str):
        try:
            service.get_run(run_id)
            try:
                path = service.artifact_path(run_id, 'steps.jsonl')
                with path.open('rb') as handle:
                    size = path.stat().st_size
                    handle.seek(max(0, size - 256 * 1024))
                    text = handle.read().decode('utf-8', errors='replace')
                return api_ok(run_id=run_id, text=text, truncated=size > 256 * 1024)
            except FileNotFoundError:
                return api_ok(run_id=run_id, text='', note='No steps have started')
        except Exception as error:
            return failure(error)

    @router.get('/runs/{run_id}/file')
    async def file(run_id: str, name: str):
        try:
            path = service.artifact_path(run_id, name)
            return FileResponse(path, filename=path.name)
        except Exception as error:
            return failure(error)

    return router
