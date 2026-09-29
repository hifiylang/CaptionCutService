"""定位 rich caption、按 segment 边界切分并重建 Global 信息。"""

from __future__ import annotations

import copy
import json
import math
import time
from pathlib import PurePosixPath
from typing import Any, Protocol

import requests

from caption_cut_service.config import Settings
from caption_cut_service.schemas import CaptionCutRequest, CaptionCutResult
from caption_cut_service.storage import OssStorage

OUTCOMES = {
    "success_without_recovery",
    "success_with_recovery",
    "partial",
    "failure",
    "unknown",
}


class GlobalSummarizer(Protocol):
    """根据所选 segments 生成当前片段的双语任务摘要。"""

    def __call__(self, source_task: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]: ...


def _localized(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"Global summary {field} must be an object")
    result = {language: str(value.get(language, "")).strip() for language in ("en", "zh")}
    if not all(result.values()):
        raise ValueError(f"Global summary {field} must contain non-empty en and zh")
    return result


class ArkGlobalSummarizer:
    """调用 Ark 文本模型，仅重写 Global task 的自然语言字段。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.system_prompt = settings.prompt_path.read_text(encoding="utf-8").strip()
        if not self.system_prompt:
            raise ValueError("Global summary prompt is empty")

    def __call__(self, source_task: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
        """生成并严格裁剪 command、step 与可选 outcome。"""
        if not self.settings.ark_api_key:
            raise RuntimeError("ARK_API_KEY is required")
        evidence = {
            "source_task": source_task,
            "segments": segments,
        }
        payload = {
            "model": self.settings.ark_model,
            "instructions": self.system_prompt,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                        }
                    ],
                }
            ],
            "max_output_tokens": 2048,
            "thinking": {"type": "disabled"},
            "store": False,
            "stream": False,
        }
        raw = self._post(payload)
        texts = [
            content["text"]
            for item in raw.get("output", [])
            if isinstance(item, dict)
            for content in item.get("content", [])
            if isinstance(content, dict) and isinstance(content.get("text"), str)
        ]
        result = json.loads("".join(texts))
        if not isinstance(result, dict):
            raise ValueError("Global model output must be a JSON object")
        summary: dict[str, Any] = {
            "command": _localized(result.get("command"), "command"),
            "step": _localized(result.get("step"), "step"),
        }
        outcome = result.get("outcome")
        if outcome is not None:
            if outcome not in OUTCOMES:
                raise ValueError("Global summary outcome is outside the closed set")
            summary["outcome"] = outcome
        return summary

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """重试临时网络、限流和服务端错误，不在异常中暴露鉴权头。"""
        headers = {
            "Authorization": f"Bearer {self.settings.ark_api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(1, self.settings.global_retry_attempts + 1):
            try:
                response = requests.post(
                    f"{self.settings.ark_base_url}/responses",
                    headers=headers,
                    json=payload,
                    timeout=(30, self.settings.global_timeout_seconds),
                )
            except requests.RequestException as exc:
                if attempt >= self.settings.global_retry_attempts:
                    raise RuntimeError(f"Global model request failed: {type(exc).__name__}") from exc
                time.sleep(2 ** (attempt - 1))
                continue
            if (response.status_code == 429 or response.status_code >= 500) and (
                attempt < self.settings.global_retry_attempts
            ):
                time.sleep(2 ** (attempt - 1))
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"Global model returned HTTP {response.status_code}")
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("Global model response must be a JSON object")
            return value
        raise AssertionError("unreachable")


def _segment_times(segment: Any, index: int) -> tuple[float, float]:
    if not isinstance(segment, dict):
        raise ValueError(f"segments[{index}] must be an object")
    try:
        start = float(segment["start_time"])
        end = float(segment["end_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"segments[{index}] has invalid time fields") from exc
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError(f"segments[{index}] has invalid time range")
    return start, end


def select_segments(
    segments: Any,
    *,
    requested_start: float,
    requested_end: float,
) -> tuple[list[dict[str, Any]], float, float]:
    """选择与请求区间相交的完整 segments，并把时间轴重置到首段起点。"""
    if not isinstance(segments, list) or not segments:
        raise ValueError("Caption segments must be a non-empty array")
    selected: list[tuple[dict[str, Any], float, float]] = []
    previous_end = 0.0
    for index, segment in enumerate(segments):
        start, end = _segment_times(segment, index)
        if index and start < previous_end - 0.001:
            raise ValueError("Caption segments must be ordered and non-overlapping")
        previous_end = end
        if end > requested_start and start < requested_end:
            selected.append((segment, start, end))
    if not selected:
        raise ValueError("Requested frame range does not overlap any caption segment")

    expanded_start = selected[0][1]
    expanded_end = selected[-1][2]
    rebased: list[dict[str, Any]] = []
    for segment, start, end in selected:
        item = copy.deepcopy(segment)
        item["start_time"] = round(start - expanded_start, 6)
        item["end_time"] = round(end - expanded_start, 6)
        rebased.append(item)
    return rebased, expanded_start, expanded_end


class CaptionCutService:
    """编排单个 Caption 切分任务，并只向固定 OSS 前缀交付结果。"""

    def __init__(
        self,
        settings: Settings,
        storage: OssStorage,
        summarizer: GlobalSummarizer | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.summarizer = summarizer or ArkGlobalSummarizer(settings)

    def cut(self, request: CaptionCutRequest, task_id: str) -> CaptionCutResult:
        """完成切分与上传，并返回来源、交付地址和实际切分范围。"""
        caption = self._find_caption(request.source_oss_uri)
        source_video_oss_uri = caption.get("video_oss_uri")
        if not isinstance(source_video_oss_uri, str) or not source_video_oss_uri.startswith("oss://"):
            if request.source_oss_uri.lower().endswith(".json") or request.source_oss_uri.endswith("/"):
                raise ValueError("Caption JSON must contain video_oss_uri")
            source_video_oss_uri = request.source_oss_uri
        requested_start = float(request.start_frame)
        requested_end = float(request.end_frame)
        selected, expanded_start, expanded_end = select_segments(
            caption.get("segments"),
            requested_start=requested_start,
            requested_end=requested_end,
        )

        source_scene = caption.get("scene")
        source_task = caption.get("task")
        if not isinstance(source_scene, dict) or not isinstance(source_task, dict):
            raise ValueError("Caption must contain scene and task objects")
        summary = self.summarizer(source_task, selected)
        task = {
            "command": summary["command"],
            "step": summary["step"],
            **{key: source_task[key] for key in ("domain", "type") if key in source_task},
        }
        if "outcome" in summary:
            task["outcome"] = summary["outcome"]
        result = {"scene": copy.deepcopy(source_scene), "task": task, "segments": selected}

        result_name = f"{task_id}_rich_caption_{request.start_frame}_{request.end_frame}.json"
        result_uri = f"{self.settings.output_oss_prefix}/{result_name}"
        staging_path = self.settings.task_staging_dir / task_id / "result.json"
        self.storage.upload_json(result, result_uri, staging_path)
        return CaptionCutResult(
            source_video_oss_uri=source_video_oss_uri,
            result_oss_uri=result_uri,
            start_frame=math.floor(expanded_start),
            end_frame=math.ceil(expanded_end),
        )

    def _find_caption(self, uri: str) -> dict[str, Any]:
        """优先读取确定性文件名，再用 video_oss_uri 消除同目录多候选歧义。"""
        if uri.lower().endswith(".json"):
            return self.storage.read_json(uri)

        if not uri.endswith("/"):
            bucket, key = uri.removeprefix("oss://").split("/", 1)
            source = PurePosixPath(key)
            exact = f"oss://{bucket}/{(source.parent / f'{source.stem}_rich_caption.json').as_posix()}"
            if self.storage.object_exists(exact):
                payload = self.storage.read_json(exact)
                archived_source = payload.get("video_oss_uri")
                if archived_source in (None, uri):
                    return payload

        candidates = self.storage.list_rich_captions(uri)
        matches: list[dict[str, Any]] = []
        for candidate in candidates:
            payload = self.storage.read_json(candidate)
            if payload.get("video_oss_uri") == uri:
                matches.append(payload)
        if len(matches) == 1:
            return matches[0]
        if uri.endswith("/") and len(candidates) == 1:
            return self.storage.read_json(candidates[0])
        if not matches:
            raise FileNotFoundError("No rich caption matched the requested OSS path")
        raise ValueError("Multiple rich captions matched the requested OSS path")
