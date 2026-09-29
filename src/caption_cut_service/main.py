"""CaptionCutService 的 FastAPI 应用工厂与标准 ASGI 入口。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from caption_cut_service.api.routes import router
from caption_cut_service.config import get_settings
from caption_cut_service.logging import configure_logging, log_event
from caption_cut_service.services.caption import CaptionCutService
from caption_cut_service.storage import OssStorage

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """创建同步请求共享的 OSS 与 Caption 切分服务。"""
    settings = get_settings()
    settings.staging_dir.mkdir(parents=True, exist_ok=True)
    application.state.caption_cut_service = CaptionCutService(settings, OssStorage(settings))
    log_event(LOGGER, "api_started", version=settings.app_version)
    try:
        yield
    finally:
        log_event(LOGGER, "api_stopped")


def create_app() -> FastAPI:
    """按集中配置创建并装配 FastAPI 应用。"""
    settings = get_settings()
    configure_logging(level=settings.log_level, log_dir=settings.log_dir)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.include_router(router)
    return application


app = create_app()


def main() -> None:
    """启动常驻 API 服务。"""
    settings = get_settings()
    uvicorn.run(
        "caption_cut_service.main:app",
        host=settings.host,
        port=settings.port,
        loop="asyncio",
        http="h11",
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
