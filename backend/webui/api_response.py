"""Small response helpers for WebUI APIs.

Contract:
    success -> {"ok": true, ...payload}
    failure -> {"ok": false, "error": str, "message": str, "code": str?}

HTTP status codes remain meaningful. New/changed endpoints should use these
helpers so frontend error handling can stay shared.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse


def api_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    **extra,
) -> JSONResponse:
    payload = {
        "ok": False,
        "error": code or message,
        "message": message,
    }
    if code:
        payload["code"] = code
    payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)


def api_ok(**data):
    return {"ok": True, **data}
