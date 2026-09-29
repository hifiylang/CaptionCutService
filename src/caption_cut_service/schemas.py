"""Caption 切分请求、异步任务与结果查询协议。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

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

    startframe: int = Field(ge=0, description="切分起始帧，包含该帧")
    endframe: int = Field(gt=0, description="切分结束帧，按右开区间处理")
    osspath: str = Field(min_length=1, description="源视频、rich caption 或其所在 OSS 目录")

    @model_validator(mode="after")
    def validate_frame_range(self):
        """拒绝空区间，避免 segment 边界匹配产生歧义。"""
        if self.endframe <= self.startframe:
            raise ValueError("endframe must be greater than startframe")
        if not self.osspath.startswith("oss://"):
            raise ValueError("osspath must be an oss:// URI")
        return self


class CaptionCutSubmission(BaseModel):
    """任务提交后的 202 响应。"""

    task_id: str
    status: JobStatus
    status_url: str


class CaptionCutTask(BaseModel):
    """任务查询响应；成功时 result 保存 OSS 地址与实际扩展边界。"""

    task_id: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str
