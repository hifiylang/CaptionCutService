"""统一结构化日志、成功失败分流和敏感字段脱敏。"""

from __future__ import annotations

import json
import logging
import re
import socket
from datetime import UTC, datetime
from logging.config import dictConfig
from pathlib import Path
from typing import Any

_HOSTNAME = socket.gethostname()
_SENSITIVE_KEYS = ("password", "secret", "api_key", "access_key", "authorization", "security_token")
_URL_CREDENTIALS = re.compile(r"([a-z][a-z0-9+.-]*://)([^/@\s:]+):([^/@\s]+)@", re.IGNORECASE)
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:ossaccesskeyid|signature|securitytoken|x-oss-security-token|x-amz-credential|x-amz-signature)=)"
    r"[^&\s]+"
)
_NAMED_SECRET = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?key|security[_-]?token|password|secret)"
    r"\s*([=:])\s*([^\s,;&]+(?:\s+[^\s,;&]+)?)"
)


def _safe_text(value: object) -> str:
    text = _URL_CREDENTIALS.sub(r"\1***:***@", str(value))
    text = _QUERY_SECRET.sub(r"\1***", text)
    text = _NAMED_SECRET.sub(r"\1\2***", text)
    return text if len(text) <= 4000 else f"{text[:4000]}..."


def _sanitize(value: Any, key: str = "") -> Any:
    """递归清理结构化字段中的凭证与不可序列化值。"""
    normalized = key.lower().replace("-", "_")
    if key and any(part in normalized for part in _SENSITIVE_KEYS):
        return "***"
    if isinstance(value, dict):
        return {str(item_key): _sanitize(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value)


class JsonLogFormatter(logging.Formatter):
    """把应用日志格式化为适合检索和容器采集的单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        event = _safe_text(getattr(record, "event", record.getMessage()))
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": "caption-cut-service",
            "component": record.name,
            "host": _HOSTNAME,
            "process_id": record.process,
            "thread": record.threadName,
            "event": event,
        }
        payload.update(_sanitize(getattr(record, "fields", {})))
        if record.exc_info:
            payload["exception"] = _safe_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_safe_text)


class EventFilter(logging.Filter):
    """只允许指定稳定事件进入对应终态日志。"""

    def __init__(self, events: tuple[str, ...]) -> None:
        super().__init__()
        self.events = frozenset(events)

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "event", "") in self.events


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """记录具有稳定事件名和结构化字段的日志。"""
    logger.log(level, event, extra={"event": event, "fields": fields}, exc_info=exc_info)


def configure_logging(*, level: str, log_dir: Path) -> None:
    """配置 JSON 控制台日志和按日轮转的成功、失败日志。"""
    success_dir = log_dir / "success"
    failure_dir = log_dir / "failure"
    success_dir.mkdir(parents=True, exist_ok=True)
    failure_dir.mkdir(parents=True, exist_ok=True)
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonLogFormatter}},
            "filters": {
                "success": {"()": EventFilter, "events": ("caption_cut_succeeded",)},
                "failure": {"()": EventFilter, "events": ("caption_cut_failed",)},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                },
                "success": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "formatter": "json",
                    "filters": ["success"],
                    "filename": str(success_dir / "caption-cut-success.log"),
                    "when": "midnight",
                    "backupCount": 30,
                    "encoding": "utf-8",
                    "utc": True,
                },
                "failure": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "formatter": "json",
                    "filters": ["failure"],
                    "filename": str(failure_dir / "caption-cut-failure.log"),
                    "when": "midnight",
                    "backupCount": 30,
                    "encoding": "utf-8",
                    "utc": True,
                },
            },
            "root": {"handlers": ["console", "success", "failure"], "level": level},
            "loggers": {
                "uvicorn.error": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
                "urllib3": {"level": "WARNING"},
                "oss2": {"level": "WARNING"},
                "asyncio": {"level": "WARNING"},
            },
        }
    )
