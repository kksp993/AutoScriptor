"""Read-only script API documentation; normal WebUI authentication still applies."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.script_api_reference import build_reference, get_version_metadata


router = APIRouter(prefix="/api/script-api", tags=["Script API reference"])


@router.get("/version")
def script_api_version():
    return JSONResponse(get_version_metadata(), headers={"Cache-Control": "no-store"})


@router.get("/reference")
def script_api_reference():
    return JSONResponse(build_reference(), headers={"Cache-Control": "no-store"})
