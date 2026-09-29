"""Caption 同步切分与健康检查路由。"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request, status

from caption_cut_service.schemas import CaptionCutRequest, CaptionCutResponse
from caption_cut_service.services.caption import CaptionCutService

router = APIRouter()
caption_cuts = APIRouter(prefix="/api/caption-cuts", tags=["caption-cuts"])


def _service(request: Request) -> CaptionCutService:
    return cast(CaptionCutService, request.app.state.caption_cut_service)


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """返回进程存活状态。"""
    return {"status": "ok"}


@caption_cuts.post(
    "",
    response_model=CaptionCutResponse,
    summary="切分 Caption",
)
def cut_caption(payload: CaptionCutRequest, request: Request) -> CaptionCutResponse:
    """等待完整切分与上传完成，再直接返回业务结果。"""
    try:
        result = _service(request).cut(payload)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return CaptionCutResponse(
        start_frame=payload.start_frame,
        end_frame=payload.end_frame,
        result=result,
    )


router.include_router(caption_cuts)
