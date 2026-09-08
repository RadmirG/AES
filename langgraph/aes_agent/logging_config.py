from __future__ import annotations

import json
import logging
import logging.config
import os
import re
import threading
from collections import deque
from datetime import datetime, timezone
from itertools import islice
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

_RECENT_LOG_LOCK = threading.Lock()
_RECENT_LOG_SEQUENCE = 0
_RECENT_LOGS: deque[dict[str, Any]] = deque(
    maxlen=max(100, int(os.getenv("AES_RECENT_LOG_CAPACITY", "3000")))
)


class ComponentFilter(logging.Filter):
    def __init__(self, component: str) -> None:
        super().__init__()
        self.component = component

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = self.component
        return True


class RecentLogHandler(logging.Handler):
    """Keep a bounded, redacted application-log window for the Workbench."""

    def emit(self, record: logging.LogRecord) -> None:
        global _RECENT_LOG_SEQUENCE
        try:
            raw_message = record.getMessage()
            if record.exc_info:
                raw_message = (
                    f"{raw_message}\n"
                    f"{logging.Formatter().formatException(record.exc_info)}"
                )
            limit = int(os.getenv("AES_RECENT_LOG_MAX_CHARS", "4000"))
            message = _truncate(_sanitize_string(_truncate(raw_message, limit)), limit)
            entry = {
                "sequence": 0,
                "timestamp": datetime.fromtimestamp(
                    record.created,
                    tz=timezone.utc,
                ).isoformat(),
                "component": str(
                    getattr(record, "component", DEFAULT_COMPONENT_NAME)
                ),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
            with _RECENT_LOG_LOCK:
                _RECENT_LOG_SEQUENCE += 1
                entry["sequence"] = _RECENT_LOG_SEQUENCE
                _RECENT_LOGS.append(entry)
        except Exception:
            self.handleError(record)


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
                },
                "recent": {
                    "()": RecentLogHandler,
                    "filters": ["component"],
                }
            },
            "root": {
                "handlers": ["console", "recent"],
                "level": level,
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["console", "recent"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console", "recent"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console", "recent"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )


def recent_log_entries(*, after: int = 0, limit: int = 400) -> list[dict[str, Any]]:
    """Return a stable copy of recent log entries after a sequence number."""
    bounded_limit = max(1, min(limit, 1000))
    with _RECENT_LOG_LOCK:
        matching = [entry for entry in _RECENT_LOGS if entry["sequence"] > after]
        return [dict(entry) for entry in matching[-bounded_limit:]]


def content_logging_enabled() -> bool:
    return os.getenv("AES_LOG_CONTENT", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def log_value(value: Any, *, max_chars: int | None = None) -> str:
    max_chars = max_chars or int(os.getenv("AES_LOG_MAX_CHARS", "1200"))
    sanitized = _sanitize(value, max_chars=max_chars)
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
    if not logger.isEnabledFor(level) or not content_logging_enabled():
        return
    logger.log(level, "%s content=%s", message, log_value(value, max_chars=max_chars))


def _sanitize(
    value: Any, *, max_chars: int = 1200,
    budget: list[int] | None = None, depth: int = 0,
) -> Any:
    # Bound work before serializing: result objects include full meshes and file bytes.
    if budget is None:
        budget = [200]
    if budget[0] <= 0 or depth >= 8:
        return "[omitted: preview limit]"
    budget[0] -= 1
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in islice(value.items(), 20):
            if budget[0] <= 0:
                break
            key_text = _truncate(str(key), max_chars)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "***redacted***"
            else:
                sanitized[key_text] = _sanitize(
                    item, max_chars=max_chars, budget=budget, depth=depth + 1,
                )
        if len(sanitized) < len(value):
            sanitized["[omitted]"] = f"{len(value) - len(sanitized)} more entries"
        return sanitized
    if isinstance(value, (list, tuple)):
        sanitized = []
        for item in islice(value, 20):
            if budget[0] <= 0:
                break
            sanitized.append(_sanitize(
                item, max_chars=max_chars, budget=budget, depth=depth + 1,
            ))
        if len(sanitized) < len(value):
            sanitized.append(f"[omitted: {len(value) - len(sanitized)} more items]")
        return sanitized
    if isinstance(value, str):
        return _sanitize_string(_truncate(value, max_chars))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"[{type(value).__name__}]"


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
