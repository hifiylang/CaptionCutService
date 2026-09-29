"""Caption 切分任务的 RESTful 提交、查询与健康检查路由。"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status

from caption_cut_service.schemas import CaptionCutRequest, CaptionCutSubmission, CaptionCutTask
from caption_cut_service.services.jobs import CaptionCutJobs

router = APIRouter()
caption_cuts = APIRouter(prefix="/api/caption-cuts", tags=["caption-cuts"])


def _jobs(request: Request) -> CaptionCutJobs:
    return cast(CaptionCutJobs, request.app.state.caption_cut_jobs)


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """返回进程存活状态。"""
    return {"status": "ok"}


@caption_cuts.post(
    "",
    response_model=CaptionCutSubmission,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交 Caption 切分任务",
)
def create_caption_cut(payload: CaptionCutRequest, request: Request, response: Response) -> CaptionCutSubmission:
    """登记请求并立即返回任务地址，处理工作由后台线程完成。"""
    task = _jobs(request).submit(payload)
    status_url = str(request.url_for("get_caption_cut", task_id=task.task_id))
    response.headers["Location"] = status_url
    return CaptionCutSubmission(task_id=task.task_id, status=task.status, status_url=status_url)


@caption_cuts.get(
    "/{task_id}",
    response_model=CaptionCutTask,
    summary="查询 Caption 切分任务",
)
def get_caption_cut(task_id: str, request: Request) -> CaptionCutTask:
    """返回任务当前状态；成功时包含结果 OSS 地址与扩展后帧范围。"""
    task = _jobs(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caption cut task not found")
    return task


router.include_router(caption_cuts)
