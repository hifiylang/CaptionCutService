"""集中加载 CaptionCutService 的固定配置与外部凭证。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "Caption Cut Service"
APP_VERSION = "0.1.0"
APP_HOST = "0.0.0.0"
APP_PORT = 8010
OSS_ENDPOINT = "https://oss-cn-shanghai-internal.aliyuncs.com"
OUTPUT_OSS_PREFIX = "oss://ss-oss-intern/user/mengjun/CaptionCutService"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL = "ep-20260730105409-w8q5r"
GLOBAL_TIMEOUT_SECONDS = 120
GLOBAL_RETRY_ATTEMPTS = 3
OSS_RETRY_ATTEMPTS = 5
OSS_CONNECT_TIMEOUT_SECONDS = 15
MAX_CAPTION_BYTES = 16 * 1024 * 1024
MAX_CAPTION_CANDIDATES = 200
LOG_LEVEL = "INFO"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "global_summary.txt"
LOG_DIR = DATA_DIR / "logs"
_ENV_NAMES = {
    "CAPTION_CUT_HOST",
    "CAPTION_CUT_PORT",
    "CAPTION_CUT_DATA_DIR",
    "CAPTION_CUT_LOG_DIR",
    "CAPTION_CUT_LOG_LEVEL",
    "OSS_ACCESS_KEY_ID",
    "OSS_ACCESS_KEY_SECRET",
    "OSS_SECURITY_TOKEN",
    "OSS_ENDPOINT",
    "ARK_API_KEY",
    "ARK_BASE_URL",
    "ARK_MODEL",
    "GLOBAL_TIMEOUT_SECONDS",
    "GLOBAL_RETRY_ATTEMPTS",
    "OSS_RETRY_ATTEMPTS",
    "OSS_CONNECT_TIMEOUT_SECONDS",
    "MAX_CAPTION_BYTES",
    "MAX_CAPTION_CANDIDATES",
}


def load_environment() -> None:
    """只加载本项目 `.env` 中声明支持的配置与凭证。"""
    configured = os.environ.get("CAPTION_CUT_ENV_FILE")
    path = Path(configured) if configured else PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        name = key.strip()
        if separator and name in _ENV_NAMES:
            os.environ.setdefault(name, value.strip().strip("\"'"))


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    """进程启动后共享的只读运行配置。"""

    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    host: str = APP_HOST
    port: int = APP_PORT
    data_dir: Path = DATA_DIR
    prompt_path: Path = PROMPT_PATH
    output_oss_prefix: str = OUTPUT_OSS_PREFIX
    oss_endpoint: str = OSS_ENDPOINT
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_security_token: str | None = None
    ark_api_key: str | None = None
    ark_base_url: str = ARK_BASE_URL
    ark_model: str = ARK_MODEL
    global_timeout_seconds: int = GLOBAL_TIMEOUT_SECONDS
    global_retry_attempts: int = GLOBAL_RETRY_ATTEMPTS
    oss_retry_attempts: int = OSS_RETRY_ATTEMPTS
    oss_connect_timeout_seconds: int = OSS_CONNECT_TIMEOUT_SECONDS
    max_caption_bytes: int = MAX_CAPTION_BYTES
    max_caption_candidates: int = MAX_CAPTION_CANDIDATES
    log_level: str = LOG_LEVEL
    log_dir: Path = LOG_DIR

    @property
    def staging_dir(self) -> Path:
        """返回结果上传前的原子暂存目录。"""
        return self.data_dir / "staging"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """组合固定配置与环境注入的凭证，并检查写入边界。"""
    load_environment()
    data_dir = _env_path("CAPTION_CUT_DATA_DIR", DATA_DIR)
    settings = Settings(
        host=os.environ.get("CAPTION_CUT_HOST", APP_HOST),
        port=_env_int("CAPTION_CUT_PORT", APP_PORT),
        data_dir=data_dir,
        oss_endpoint=os.environ.get("OSS_ENDPOINT", OSS_ENDPOINT),
        oss_access_key_id=os.environ.get("OSS_ACCESS_KEY_ID") or None,
        oss_access_key_secret=os.environ.get("OSS_ACCESS_KEY_SECRET") or None,
        oss_security_token=os.environ.get("OSS_SECURITY_TOKEN") or None,
        ark_api_key=os.environ.get("ARK_API_KEY") or None,
        ark_base_url=os.environ.get("ARK_BASE_URL", ARK_BASE_URL),
        ark_model=os.environ.get("ARK_MODEL", ARK_MODEL),
        global_timeout_seconds=_env_int("GLOBAL_TIMEOUT_SECONDS", GLOBAL_TIMEOUT_SECONDS),
        global_retry_attempts=_env_int("GLOBAL_RETRY_ATTEMPTS", GLOBAL_RETRY_ATTEMPTS),
        oss_retry_attempts=_env_int("OSS_RETRY_ATTEMPTS", OSS_RETRY_ATTEMPTS),
        oss_connect_timeout_seconds=_env_int("OSS_CONNECT_TIMEOUT_SECONDS", OSS_CONNECT_TIMEOUT_SECONDS),
        max_caption_bytes=_env_int("MAX_CAPTION_BYTES", MAX_CAPTION_BYTES),
        max_caption_candidates=_env_int("MAX_CAPTION_CANDIDATES", MAX_CAPTION_CANDIDATES),
        log_level=os.environ.get("CAPTION_CUT_LOG_LEVEL", LOG_LEVEL).upper(),
        log_dir=_env_path("CAPTION_CUT_LOG_DIR", data_dir / "logs"),
    )
    parsed = urlparse(settings.output_oss_prefix)
    if parsed.scheme != "oss" or parsed.netloc != "ss-oss-intern":
        raise ValueError("OUTPUT_OSS_PREFIX must stay inside oss://ss-oss-intern")
    return settings
