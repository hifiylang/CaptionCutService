"""Caption 切分请求、异步任务与结果查询协议。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobStatus(StrEnum):
    """异步任务在当前进程内的状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CaptionCutRequest(BaseModel):
    """外部提交的三个业务参数。"""

    model_config = ConfigDict(extra="forbid")

    start_frame: int = Field(ge=0, description="切分起始帧，包含该帧")
    end_frame: int = Field(gt=0, description="切分结束帧，按右开区间处理")
    source_oss_uri: str = Field(min_length=1, description="源视频、rich caption 或其所在 OSS 目录 URI")

    @model_validator(mode="after")
    def validate_frame_range(self):
        """拒绝空区间，避免 segment 边界匹配产生歧义。"""
        if self.end_frame <= self.start_frame:
            raise ValueError("end_frame must be greater than start_frame")
        if not self.source_oss_uri.startswith("oss://"):
            raise ValueError("source_oss_uri must be an oss:// URI")
        return self


class CaptionCutSubmission(BaseModel):
    """任务提交后的 202 响应。"""

    task_id: str
    status: JobStatus
    status_url: str


class CaptionCutResult(BaseModel):
    """成功任务返回的来源、交付地址和实际切分边界。"""

    model_config = ConfigDict(extra="forbid")

    result_oss_uri: str
    source_caption_oss_uri: str
    source_video_oss_uri: str
    requested_start_frame: int = Field(ge=0)
    requested_end_frame: int = Field(gt=0)
    expanded_start_frame: int = Field(ge=0)
    expanded_end_frame: int = Field(gt=0)
    segment_count: int = Field(gt=0)


class CaptionCutTask(BaseModel):
    """任务查询响应；成功时 result 保存 OSS 地址与实际扩展边界。"""

    task_id: str
    status: JobStatus
    result: CaptionCutResult | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
