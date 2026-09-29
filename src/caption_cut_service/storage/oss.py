"""阿里云 OSS 对象发现、读取、FPS 探测与结果上传。"""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from fractions import Fraction
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar
from urllib.parse import unquote, urlparse

import oss2

from caption_cut_service.config import Settings

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


def parse_oss_uri(uri: str) -> tuple[str, str]:
    """把 `oss://bucket/key` 拆分为 bucket 与对象键。"""
    parsed = urlparse(uri)
    key = unquote(parsed.path.lstrip("/"))
    if parsed.scheme != "oss" or not parsed.netloc or not key:
        raise ValueError(f"Invalid OSS URI: {uri}")
    return parsed.netloc, key


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (oss2.exceptions.RequestError, TimeoutError, ConnectionError)):
        return True
    status = int(getattr(exc, "status", 0) or 0)
    return status == 429 or status >= 500


def _retry(operation: str, call: Callable[[], T], attempts: int) -> T:
    """以有限指数退避执行幂等 OSS 操作。"""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not _retryable(exc) or attempt >= attempts:
                raise
            delay = 2 ** (attempt - 1)
            LOGGER.warning(
                "oss_request_retry operation=%s attempt=%s max_attempts=%s error_type=%s",
                operation,
                attempt,
                attempts,
                type(exc).__name__,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


@lru_cache(maxsize=32)
def _bucket(bucket_name: str, settings: Settings) -> oss2.Bucket:
    """按环境凭证创建并缓存指定 bucket 的客户端。"""
    if not settings.oss_access_key_id or not settings.oss_access_key_secret:
        raise RuntimeError("OSS_ACCESS_KEY_ID and OSS_ACCESS_KEY_SECRET are required")
    if settings.oss_security_token:
        auth = oss2.StsAuth(
            settings.oss_access_key_id,
            settings.oss_access_key_secret,
            settings.oss_security_token,
        )
    else:
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(
        auth,
        settings.oss_endpoint,
        bucket_name,
        connect_timeout=settings.oss_connect_timeout_seconds,
    )


class OssStorage:
    """封装 CaptionCutService 允许执行的全部 OSS 操作。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def object_exists(self, uri: str) -> bool:
        """检查对象是否存在，不把权限或网络故障伪装成不存在。"""
        bucket_name, key = parse_oss_uri(uri)
        bucket = _bucket(bucket_name, self.settings)
        try:
            _retry("object_exists", lambda: bucket.head_object(key), self.settings.oss_retry_attempts)
        except oss2.exceptions.NoSuchKey:
            return False
        return True

    def read_json(self, uri: str) -> dict[str, Any]:
        """读取受大小限制的 JSON 对象，并保证顶层是对象。"""
        bucket_name, key = parse_oss_uri(uri)
        bucket = _bucket(bucket_name, self.settings)
        metadata = _retry("caption_head", lambda: bucket.head_object(key), self.settings.oss_retry_attempts)
        size = int(metadata.content_length)
        if size <= 0 or size > self.settings.max_caption_bytes:
            raise ValueError(f"Caption object size is invalid: {size}")
        raw = _retry("caption_read", lambda: bucket.get_object(key).read(), self.settings.oss_retry_attempts)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Caption JSON root must be an object")
        return value

    def list_rich_captions(self, uri: str) -> list[str]:
        """在输入对象的同目录或显式目录下列出 rich caption 候选。"""
        bucket_name, key = parse_oss_uri(uri)
        if key.endswith("/"):
            prefix = key
        else:
            source = PurePosixPath(key)
            prefix = (source.parent / source.stem).as_posix()
        bucket = _bucket(bucket_name, self.settings)

        def collect() -> list[str]:
            result: list[str] = []
            for item in oss2.ObjectIteratorV2(bucket, prefix=prefix, max_keys=1000):
                if item.key.endswith("_rich_caption.json"):
                    result.append(f"oss://{bucket_name}/{item.key}")
                    if len(result) > self.settings.max_caption_candidates:
                        raise ValueError("Too many rich caption candidates under OSS prefix")
            return sorted(result)

        return _retry("caption_list", collect, self.settings.oss_retry_attempts)

    def probe_video_fps(self, video_uri: str) -> float:
        """通过短期内网签名 URL 读取视频平均帧率，不下载完整视频。"""
        bucket_name, key = parse_oss_uri(video_uri)
        bucket = _bucket(bucket_name, self.settings)
        signed_url = bucket.sign_url("GET", key, 300, slash_safe=True)
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            signed_url,
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.ffprobe_timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # 签名 URL 含凭证信息，异常中不得附带 command 或 stderr。
            raise RuntimeError(f"Unable to probe source video FPS: {type(exc).__name__}") from exc
        payload = json.loads(completed.stdout)
        streams = payload.get("streams")
        if not isinstance(streams, list) or not streams:
            raise ValueError("Source video has no video stream")
        for field in ("avg_frame_rate", "r_frame_rate"):
            raw = streams[0].get(field)
            try:
                fps = float(Fraction(str(raw)))
            except (ValueError, ZeroDivisionError):
                continue
            if math.isfinite(fps) and 0 < fps <= 240:
                return fps
        raise ValueError("Source video FPS is missing or invalid")

    def upload_json(self, value: dict[str, Any], uri: str, staging_path: Path) -> str:
        """原子暂存 JSON、上传到 OSS，并校验远端对象长度。"""
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{staging_path.name}.",
            suffix=".tmp",
            dir=staging_path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(value, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, staging_path)
        finally:
            temporary.unlink(missing_ok=True)

        bucket_name, key = parse_oss_uri(uri)
        expected_size = staging_path.stat().st_size
        bucket = _bucket(bucket_name, self.settings)
        response = _retry(
            "result_upload",
            lambda: bucket.put_object_from_file(key, str(staging_path)),
            self.settings.oss_retry_attempts,
        )
        if int(response.status) not in {200, 201}:
            raise OSError(f"OSS upload returned HTTP {response.status}")
        metadata = _retry("result_head", lambda: bucket.head_object(key), self.settings.oss_retry_attempts)
        if int(metadata.content_length) != expected_size:
            raise OSError("OSS upload size mismatch")
        return uri
