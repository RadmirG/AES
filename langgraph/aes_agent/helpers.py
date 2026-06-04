from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import requests


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama-server:11434")
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
#OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b")
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
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": OLLAMA_NUM_CTX
        }
    }

    try:
        response = requests.post(
            OLLAMA_GENERATE_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("Ollama request timed out.") from exc

    data = response.json()
    model_text = data.get("response", "")
    return extract_json_object(model_text)


def safe_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def safe_list_of_str(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []