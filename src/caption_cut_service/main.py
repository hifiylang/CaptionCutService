"""CaptionCutService 的 FastAPI 应用工厂与标准 ASGI 入口。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from caption_cut_service.api.routes import router
from caption_cut_service.config import get_settings
from caption_cut_service.services.caption import CaptionCutService
from caption_cut_service.services.jobs import CaptionCutJobs
from caption_cut_service.storage import OssStorage

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """创建共享 OSS、切分与任务资源，并在停机时完成在途任务。"""
    settings = get_settings()
    settings.task_staging_dir.mkdir(parents=True, exist_ok=True)
    cutter = CaptionCutService(settings, OssStorage(settings))
    jobs = CaptionCutJobs(cutter, settings.worker_concurrency)
    application.state.caption_cut_jobs = jobs
    LOGGER.info("caption_cut_api_started version=%s", settings.app_version)
    try:
        yield
    finally:
        jobs.close()
        LOGGER.info("caption_cut_api_stopped")


def create_app() -> FastAPI:
    """按集中配置创建并装配 FastAPI 应用。"""
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
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
