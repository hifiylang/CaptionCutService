"""Caption 切分请求与同步结果协议。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class CaptionCutResult(BaseModel):
    """来源、交付地址与实际切分范围。"""

    source_video_oss_uri: str
    result_oss_uri: str
    start_frame: int
    end_frame: int


class CaptionCutResponse(BaseModel):
    """同步接口响应；外层保留请求范围，内层返回实际切分结果。"""

    start_frame: int
    end_frame: int
    result: CaptionCutResult
