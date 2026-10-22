"""FastAPI application entry + scheduler lifespan."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .scheduler import start_scheduler, stop_scheduler
from .routes import admin, api, oauth, web, webhooks

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("数据库已初始化")
    try:
        from .db import session_scope
        from .sync_runs import purge_old_runs

        with session_scope() as db:
            n = purge_old_runs(db, days=7)
        if n:
            log.info("已清理 %d 条超过 7 天的 sync_runs", n)
    except Exception:
        log.exception("清理旧 sync_runs 失败")
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="飞书 ↔ Outlook 日历同步",
        version="1.1.0",
        lifespan=lifespan,
    )

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(api.health_router)
    app.include_router(api.router)
    app.include_router(oauth.router)
    app.include_router(web.router)
    app.include_router(webhooks.router)
    app.include_router(admin.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
