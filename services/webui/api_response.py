"""Small response helpers for WebUI APIs.

Keep the HTTP status code meaningful while returning one predictable error
shape to the frontend.
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
