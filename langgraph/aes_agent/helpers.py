from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List

import requests

from aes_agent.logging_config import log_content_preview


logger = logging.getLogger("aes_agent.ollama")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama-server:11434")
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:26b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))


def extract_json_object(text: str) -> Dict[str, Any]:
    """
    Try to parse a JSON object from model output.
    Returns {} if parsing fails.
    """
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {}


def ollama_json(prompt: str) -> Dict[str, Any]:
    """
    Call Ollama and request a JSON object response.
    """
    started_at = time.perf_counter()
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": OLLAMA_NUM_CTX
        }
    }
    logger.info(
        "Ollama JSON request started: model=%s endpoint=%s prompt_chars=%s timeout=%s num_ctx=%s",
        OLLAMA_MODEL,
        OLLAMA_GENERATE_URL,
        len(prompt),
        OLLAMA_TIMEOUT,
        OLLAMA_NUM_CTX,
    )
    log_content_preview(logger, "Ollama JSON prompt", {"prompt": prompt})

    try:
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "Ollama JSON request timed out: model=%s timeout=%s elapsed_ms=%.1f",
            OLLAMA_MODEL,
            OLLAMA_TIMEOUT,
            elapsed_ms,
        )
        return {}
    except requests.exceptions.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        status_code = (
            exc.response.status_code
            if exc.response is not None
            else "unknown"
        )
        body = (
            exc.response.text[:500]
            if exc.response is not None and exc.response.text
            else ""
        )
        logger.warning(
            "Ollama JSON request failed: model=%s status=%s elapsed_ms=%.1f body=%s",
            OLLAMA_MODEL,
            status_code,
            elapsed_ms,
            body,
        )
        return {}
    except requests.exceptions.RequestException as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "Ollama JSON request failed: model=%s elapsed_ms=%.1f error=%s",
            OLLAMA_MODEL,
            elapsed_ms,
            exc,
        )
        return {}

    data = response.json()
    model_text = data.get("response", "")
    parsed = extract_json_object(model_text)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "Ollama JSON request completed: model=%s status=%s response_chars=%s parsed_keys=%s elapsed_ms=%.1f",
        OLLAMA_MODEL,
        response.status_code,
        len(model_text),
        sorted(parsed.keys()),
        elapsed_ms,
    )
    log_content_preview(
        logger,
        "Ollama JSON response",
        {"raw_response": model_text, "parsed": parsed},
    )
    return parsed


def ollama_text(prompt: str) -> Dict[str, Any]:
    """Call Ollama for raw text and return AES-owned transport metadata."""
    started_at = time.perf_counter()
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    logger.info(
        (
            "Ollama text request started: model=%s endpoint=%s prompt_chars=%s "
            "timeout=%s num_ctx=%s"
        ),
        OLLAMA_MODEL,
        OLLAMA_GENERATE_URL,
        len(prompt),
        OLLAMA_TIMEOUT,
        OLLAMA_NUM_CTX,
    )
    log_content_preview(logger, "Ollama text prompt", {"prompt": prompt})

    try:
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        return _ollama_text_failure(
            "transport_timeout",
            started_at,
            message=f"Ollama request exceeded {OLLAMA_TIMEOUT} seconds.",
        )
    except requests.exceptions.HTTPError as exc:
        status_code = (
            exc.response.status_code
            if exc.response is not None
            else "unknown"
        )
        body = (
            exc.response.text[:500]
            if exc.response is not None and exc.response.text
            else ""
        )
        return _ollama_text_failure(
            "http_error",
            started_at,
            message=f"Ollama returned HTTP {status_code}: {body}",
        )
    except requests.exceptions.RequestException as exc:
        return _ollama_text_failure(
            "request_error",
            started_at,
            message=str(exc),
        )

    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        return _ollama_text_failure(
            "invalid_response",
            started_at,
            message=f"Ollama response body was not JSON: {exc}",
        )

    model_text = data.get("response")
    if not isinstance(model_text, str):
        return _ollama_text_failure(
            "invalid_response",
            started_at,
            message="Ollama response did not contain a string response field.",
        )

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    status = "completed" if model_text.strip() else "empty_response"
    result = {
        "status": status,
        "text": model_text,
        "model": OLLAMA_MODEL,
        "done_reason": str(data.get("done_reason") or ""),
        "response_chars": len(model_text),
        "elapsed_ms": elapsed_ms,
        "message": "" if status == "completed" else "Ollama returned empty text.",
    }
    logger.info(
        (
            "Ollama text request completed: model=%s status=%s "
            "done_reason=%s response_chars=%s elapsed_ms=%.1f"
        ),
        OLLAMA_MODEL,
        status,
        result["done_reason"],
        len(model_text),
        elapsed_ms,
    )
    log_content_preview(
        logger,
        "Ollama text response",
        {"raw_response": model_text, "transport": result},
    )
    return result


def _ollama_text_failure(
    status: str,
    started_at: float,
    *,
    message: str,
) -> Dict[str, Any]:
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.warning(
        "Ollama text request failed: model=%s status=%s message=%s elapsed_ms=%.1f",
        OLLAMA_MODEL,
        status,
        message,
        elapsed_ms,
    )
    return {
        "status": status,
        "text": "",
        "model": OLLAMA_MODEL,
        "done_reason": "",
        "response_chars": 0,
        "elapsed_ms": elapsed_ms,
        "message": message,
    }


def safe_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def safe_list_of_str(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []
