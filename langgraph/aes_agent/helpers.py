from __future__ import annotations

from typing import Any, List

from aes_agent import model_client
from aes_agent.model_client import extract_json_object, llm_json, llm_text


# Compatibility aliases keep existing graph nodes and tests stable while the
# model transport migrates from an Ollama-only client to a provider boundary.
ollama_json = llm_json
ollama_text = llm_text
requests = model_client.requests


def safe_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def safe_list_of_str(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []
