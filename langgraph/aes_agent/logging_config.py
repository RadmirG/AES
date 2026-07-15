from __future__ import annotations

import json
import logging
import logging.config
import os
import re
from typing import Any, Mapping


DEFAULT_COMPONENT_NAME = "langgraph"
DEFAULT_LOG_FORMAT = (
    "%(component)s | %(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}


class ComponentFilter(logging.Filter):
    def __init__(self, component: str) -> None:
        super().__init__()
        self.component = component

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = self.component
        return True


def configure_logging(component: str = DEFAULT_COMPONENT_NAME) -> None:
    level = os.getenv("AES_LOG_LEVEL", "INFO").upper()
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "component": {
                    "()": ComponentFilter,
                    "component": component,
                }
            },
            "formatters": {
                "aes": {
                    "format": os.getenv("AES_LOG_FORMAT", DEFAULT_LOG_FORMAT),
                    "datefmt": os.getenv("AES_LOG_DATE_FORMAT", DEFAULT_DATE_FORMAT),
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "aes",
                    "filters": ["component"],
                }
            },
            "root": {
                "handlers": ["console"],
                "level": level,
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )


def content_logging_enabled() -> bool:
    return os.getenv("AES_LOG_CONTENT", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def log_value(value: Any, *, max_chars: int | None = None) -> str:
    max_chars = max_chars or int(os.getenv("AES_LOG_MAX_CHARS", "1200"))
    sanitized = _sanitize(value)
    try:
        text = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(sanitized)
    return _truncate(text, max_chars)


def log_content_preview(
    logger: logging.Logger,
    message: str,
    value: Any,
    *,
    level: int = logging.INFO,
    max_chars: int | None = None,
) -> None:
    if not content_logging_enabled():
        return
    logger.log(level, "%s content=%s", message, log_value(value, max_chars=max_chars))


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "***redacted***"
            else:
                sanitized[key_text] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(marker in normalized for marker in SENSITIVE_KEYS)


def _sanitize_string(value: str) -> str:
    text = value
    text = re.sub(
        r"(?i)(bearer\s+)[A-Za-z0-9._\-]+",
        r"\1***redacted***",
        text,
    )
    text = re.sub(
        r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+",
        r"\1=***redacted***",
        text,
    )
    return text


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 3)] + "..."
