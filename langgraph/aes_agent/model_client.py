from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Tuple

import requests

from aes_agent.logging_config import log_content_preview


logger = logging.getLogger("aes_agent.model_client")

LLM_PROVIDER = os.getenv("AES_LLM_PROVIDER", "ollama").strip().lower()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama-server:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:26b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))

LLM_BASE_URL = os.getenv("AES_LLM_BASE_URL", "").strip()
LLM_MODEL = os.getenv("AES_LLM_MODEL", "").strip() or OLLAMA_MODEL
LLM_API_KEY = os.getenv("AES_LLM_API_KEY", "").strip()
LLM_TIMEOUT = int(os.getenv("AES_LLM_TIMEOUT", str(OLLAMA_TIMEOUT)))
LLM_MAX_TOKENS = int(os.getenv("AES_LLM_MAX_TOKENS", "4096"))
LLM_TEMPERATURE = float(os.getenv("AES_LLM_TEMPERATURE", "0.1"))


def extract_json_object(text: str) -> Dict[str, Any]:
    """Parse the first complete JSON object from model text."""
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
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {}


def llm_json(prompt: str) -> Dict[str, Any]:
    """Request a JSON object from the configured AES model provider."""
    if _normalized_provider() == "ollama":
        return _ollama_json(prompt)
    return _openai_compatible_json(prompt)


def llm_text(prompt: str) -> Dict[str, Any]:
    """Request raw text and return AES-owned transport metadata."""
    if _normalized_provider() == "ollama":
        return _ollama_text(prompt)
    return _openai_compatible_text(prompt)


def _normalized_provider() -> str:
    if LLM_PROVIDER in {"vllm", "openai", "openai_compatible"}:
        return "openai_compatible"
    if LLM_PROVIDER != "ollama":
        logger.warning(
            "Unknown AES_LLM_PROVIDER=%s; falling back to ollama.",
            LLM_PROVIDER,
        )
    return "ollama"


def _ollama_json(prompt: str) -> Dict[str, Any]:
    started_at = time.perf_counter()
    endpoint = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"num_ctx": OLLAMA_NUM_CTX},
    }
    logger.info(
        "Model JSON request started: provider=ollama model=%s endpoint=%s "
        "prompt_chars=%s timeout=%s num_ctx=%s",
        LLM_MODEL,
        endpoint,
        len(prompt),
        LLM_TIMEOUT,
        OLLAMA_NUM_CTX,
    )
    log_content_preview(logger, "Model JSON prompt", {"prompt": prompt})

    response, _, _ = _post(endpoint, payload, started_at, provider="ollama")
    if response is None:
        return {}

    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        _log_invalid_response("ollama", started_at, str(exc))
        return {}

    model_text = data.get("response", "")
    if not isinstance(model_text, str):
        _log_invalid_response("ollama", started_at, "missing response string")
        return {}

    return _complete_json_request(
        provider="ollama",
        model_text=model_text,
        status_code=response.status_code,
        started_at=started_at,
    )


def _ollama_text(prompt: str) -> Dict[str, Any]:
    started_at = time.perf_counter()
    endpoint = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": OLLAMA_NUM_CTX},
    }
    logger.info(
        "Model text request started: provider=ollama model=%s endpoint=%s "
        "prompt_chars=%s timeout=%s num_ctx=%s",
        LLM_MODEL,
        endpoint,
        len(prompt),
        LLM_TIMEOUT,
        OLLAMA_NUM_CTX,
    )
    log_content_preview(logger, "Model text prompt", {"prompt": prompt})

    response, failure_status, failure_message = _post(
        endpoint,
        payload,
        started_at,
        provider="ollama",
    )
    if response is None:
        return _text_failure(
            failure_status,
            started_at,
            provider="ollama",
            message=failure_message,
        )

    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        return _text_failure(
            "invalid_response",
            started_at,
            provider="ollama",
            message=f"Ollama response body was not JSON: {exc}",
        )

    model_text = data.get("response")
    if not isinstance(model_text, str):
        return _text_failure(
            "invalid_response",
            started_at,
            provider="ollama",
            message="Ollama response did not contain a string response field.",
        )

    return _complete_text_request(
        provider="ollama",
        model_text=model_text,
        done_reason=str(data.get("done_reason") or ""),
        started_at=started_at,
    )


def _openai_compatible_json(prompt: str) -> Dict[str, Any]:
    started_at = time.perf_counter()
    endpoint = _openai_chat_endpoint()
    payload = _openai_payload(prompt)
    payload["response_format"] = {"type": "json_object"}
    logger.info(
        "Model JSON request started: provider=%s model=%s endpoint=%s "
        "prompt_chars=%s timeout=%s max_tokens=%s",
        LLM_PROVIDER,
        LLM_MODEL,
        endpoint,
        len(prompt),
        LLM_TIMEOUT,
        LLM_MAX_TOKENS,
    )
    log_content_preview(logger, "Model JSON prompt", {"prompt": prompt})

    response, _, _ = _post(
        endpoint,
        payload,
        started_at,
        provider=LLM_PROVIDER,
        headers=_openai_headers(),
    )
    if response is None:
        return {}

    try:
        data = response.json()
        model_text, done_reason = _openai_message(data)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        _log_invalid_response(LLM_PROVIDER, started_at, str(exc))
        return {}

    parsed = _complete_json_request(
        provider=LLM_PROVIDER,
        model_text=model_text,
        status_code=response.status_code,
        started_at=started_at,
    )
    if done_reason:
        logger.debug("Model JSON finish reason: %s", done_reason)
    return parsed


def _openai_compatible_text(prompt: str) -> Dict[str, Any]:
    started_at = time.perf_counter()
    endpoint = _openai_chat_endpoint()
    payload = _openai_payload(prompt)
    logger.info(
        "Model text request started: provider=%s model=%s endpoint=%s "
        "prompt_chars=%s timeout=%s max_tokens=%s",
        LLM_PROVIDER,
        LLM_MODEL,
        endpoint,
        len(prompt),
        LLM_TIMEOUT,
        LLM_MAX_TOKENS,
    )
    log_content_preview(logger, "Model text prompt", {"prompt": prompt})

    response, failure_status, failure_message = _post(
        endpoint,
        payload,
        started_at,
        provider=LLM_PROVIDER,
        headers=_openai_headers(),
    )
    if response is None:
        return _text_failure(
            failure_status,
            started_at,
            provider=LLM_PROVIDER,
            message=failure_message,
        )

    try:
        data = response.json()
        model_text, done_reason = _openai_message(data)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return _text_failure(
            "invalid_response",
            started_at,
            provider=LLM_PROVIDER,
            message=f"OpenAI-compatible response was invalid: {exc}",
        )

    return _complete_text_request(
        provider=LLM_PROVIDER,
        model_text=model_text,
        done_reason=done_reason,
        started_at=started_at,
    )


def _openai_payload(prompt: str) -> Dict[str, Any]:
    return {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": LLM_TEMPERATURE,
    }


def _openai_chat_endpoint() -> str:
    base_url = LLM_BASE_URL or "http://aes-vllm:8000/v1"
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return f"{normalized}/chat/completions"


def _openai_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    return headers


def _openai_message(data: Dict[str, Any]) -> Tuple[str, str]:
    choice = data["choices"][0]
    model_text = choice["message"]["content"]
    if not isinstance(model_text, str):
        raise TypeError("choices[0].message.content is not a string")
    return model_text, str(choice.get("finish_reason") or "")


def _post(
    endpoint: str,
    payload: Dict[str, Any],
    started_at: float,
    *,
    provider: str,
    headers: Dict[str, str] | None = None,
):
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=LLM_TIMEOUT,
        )
        response.raise_for_status()
        return response, "", ""
    except requests.exceptions.Timeout:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "Model request timed out: provider=%s model=%s timeout=%s "
            "elapsed_ms=%.1f",
            provider,
            LLM_MODEL,
            LLM_TIMEOUT,
            elapsed_ms,
        )
        return (
            None,
            "transport_timeout",
            f"{provider} request exceeded {LLM_TIMEOUT} seconds.",
        )
    except requests.exceptions.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        body = (
            exc.response.text[:500]
            if exc.response is not None and exc.response.text
            else ""
        )
        logger.warning(
            "Model request failed: provider=%s model=%s status=%s "
            "elapsed_ms=%.1f body=%s",
            provider,
            LLM_MODEL,
            status_code,
            elapsed_ms,
            body,
        )
        return (
            None,
            "http_error",
            f"{provider} returned HTTP {status_code}: {body}",
        )
    except requests.exceptions.RequestException as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "Model request failed: provider=%s model=%s elapsed_ms=%.1f error=%s",
            provider,
            LLM_MODEL,
            elapsed_ms,
            exc,
        )
        return None, "request_error", str(exc)


def _complete_json_request(
    *,
    provider: str,
    model_text: str,
    status_code: int,
    started_at: float,
) -> Dict[str, Any]:
    parsed = extract_json_object(model_text)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "Model JSON request completed: provider=%s model=%s status=%s "
        "response_chars=%s parsed_keys=%s elapsed_ms=%.1f",
        provider,
        LLM_MODEL,
        status_code,
        len(model_text),
        sorted(parsed.keys()),
        elapsed_ms,
    )
    log_content_preview(
        logger,
        "Model JSON response",
        {"raw_response": model_text, "parsed": parsed},
    )
    return parsed


def _complete_text_request(
    *,
    provider: str,
    model_text: str,
    done_reason: str,
    started_at: float,
) -> Dict[str, Any]:
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    status = "completed" if model_text.strip() else "empty_response"
    result = {
        "status": status,
        "text": model_text,
        "model": LLM_MODEL,
        "provider": provider,
        "done_reason": done_reason,
        "response_chars": len(model_text),
        "elapsed_ms": elapsed_ms,
        "message": "" if status == "completed" else "Model returned empty text.",
    }
    logger.info(
        "Model text request completed: provider=%s model=%s status=%s "
        "done_reason=%s response_chars=%s elapsed_ms=%.1f",
        provider,
        LLM_MODEL,
        status,
        done_reason,
        len(model_text),
        elapsed_ms,
    )
    log_content_preview(
        logger,
        "Model text response",
        {"raw_response": model_text, "transport": result},
    )
    return result


def _text_failure(
    status: str,
    started_at: float,
    *,
    provider: str,
    message: str,
) -> Dict[str, Any]:
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.warning(
        "Model text request failed: provider=%s model=%s status=%s "
        "message=%s elapsed_ms=%.1f",
        provider,
        LLM_MODEL,
        status,
        message,
        elapsed_ms,
    )
    return {
        "status": status,
        "text": "",
        "model": LLM_MODEL,
        "provider": provider,
        "done_reason": "",
        "response_chars": 0,
        "elapsed_ms": elapsed_ms,
        "message": message,
    }


def _log_invalid_response(provider: str, started_at: float, message: str) -> None:
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.warning(
        "Model response invalid: provider=%s model=%s message=%s elapsed_ms=%.1f",
        provider,
        LLM_MODEL,
        message,
        elapsed_ms,
    )
