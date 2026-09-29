"""Caption 同步切分与健康检查路由。"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status

from caption_cut_service.logging import log_event
from caption_cut_service.schemas import CaptionCutRequest, CaptionCutResponse
from caption_cut_service.services.caption import CaptionCutService

LOGGER = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

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
def cut_caption(payload: CaptionCutRequest, request: Request, response: Response) -> CaptionCutResponse:
    """等待完整切分与上传完成，再直接返回业务结果。"""
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = supplied_request_id if _REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else uuid.uuid4().hex
    started = time.monotonic()
    try:
        result = _service(request).cut(payload)
    except (FileNotFoundError, ValueError) as exc:
        _log_failure(request_id, payload, exc, status.HTTP_400_BAD_REQUEST, started)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
            headers={"X-Request-ID": request_id},
        ) from exc
    except (OSError, RuntimeError) as exc:
        _log_failure(request_id, payload, exc, status.HTTP_502_BAD_GATEWAY, started)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Caption cut upstream request failed",
            headers={"X-Request-ID": request_id},
        ) from exc
    except Exception as exc:
        _log_failure(request_id, payload, exc, status.HTTP_500_INTERNAL_SERVER_ERROR, started, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
            headers={"X-Request-ID": request_id},
        ) from exc
    response.headers["X-Request-ID"] = request_id
    log_event(
        LOGGER,
        "caption_cut_succeeded",
        request_id=request_id,
        source_oss_uri=payload.source_oss_uri,
        result_oss_uri=result.result_oss_uri,
        requested_start_frame=payload.start_frame,
        requested_end_frame=payload.end_frame,
        actual_start_frame=result.start_frame,
        actual_end_frame=result.end_frame,
        elapsed_seconds=round(time.monotonic() - started, 3),
        status_code=status.HTTP_200_OK,
    )
    return CaptionCutResponse(
        start_frame=payload.start_frame,
        end_frame=payload.end_frame,
        result=result,
    )


def _log_failure(
    request_id: str,
    payload: CaptionCutRequest,
    exc: Exception,
    status_code: int,
    started: float,
    *,
    exc_info: bool = False,
) -> None:
    log_event(
        LOGGER,
        "caption_cut_failed",
        level=logging.ERROR,
        exc_info=exc_info,
        request_id=request_id,
        source_oss_uri=payload.source_oss_uri,
        requested_start_frame=payload.start_frame,
        requested_end_frame=payload.end_frame,
        status_code=status_code,
        error_type=type(exc).__name__,
        error=str(exc),
        elapsed_seconds=round(time.monotonic() - started, 3),
    )


router.include_router(caption_cuts)
