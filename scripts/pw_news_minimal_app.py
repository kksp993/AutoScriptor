"""仅挂载资讯路由，供 Playwright / 本地实验，避免拉起完整 WebUI。"""
from fastapi import FastAPI

from services.webui.routes.news import router

app = FastAPI()
app.include_router(router)
