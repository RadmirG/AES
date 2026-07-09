from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
import threading
import uuid
from typing import Any, Dict, List, Union

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from aes_agent.graph import graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(title="LangGraph Service")
logger = logging.getLogger("aes_agent")

AES_MODEL_ID = "aes-agent"
AES_RESULT_CACHE_TTL_SECONDS = 10.0
_RESULT_CACHE_LOCK = threading.Lock()
_RESULT_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}


class Query(BaseModel):
    text: str


class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = False
    temperature: float | None = None


def extract_text_from_content(content: Union[str, List[Dict[str, Any]]]) -> str:
    """
    Supports:
    - plain string content
    - OpenAI-style content blocks like [{"type":"text","text":"..."}]
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()

    return ""


def build_user_text_from_messages(messages: List[ChatMessage]) -> str:
    """
    Extract the latest user turn as the active AES request.

    OpenAI-compatible clients send the full chat history. Folding all user
    turns into one problem statement can make a new deployment/log command
    inherit an older PDE request and accidentally trigger the solver workflow.
    Until AES has checkpoint-backed multi-turn resume, the latest user message
    is the only active request.
    """
    user_texts = [
        extract_text_from_content(msg.content).strip()
        for msg in messages
        if msg.role == "user"
    ]
    user_texts = [text for text in user_texts if text]

    if not user_texts:
        return ""
    return user_texts[-1]


def run_aes_agent(user_text: str) -> Dict[str, Any]:
    """
    Internal helper that runs the LangGraph graph.
    """
    cache_key = _result_cache_key(user_text)
    cached_result = _get_cached_result(cache_key)
    if cached_result is not None:
        logger.info("AES graph invocation reused cached result.")
        return cached_result

    started_at = time.perf_counter()
    logger.info("AES graph invocation started.")
    initial_state = {
        "raw_user_input": user_text,
        "request_intent": "",
        "intent_reason": "",
        "problem_class": "",
        "domain_info": "",
        "pde_info": "",
        "coefficient_info": "",
        "source_info": "",
        "bc_info": "",
        "initial_condition_info": "",
        "time_info": "",
        "missing_information": [],
        "clarification_questions": [],
        "selected_formulation": "",
        "validation_status": "",
        "validation_errors": [],
        "numerical_recipe_status": "",
        "numerical_recipe": {},
        "numerical_recipe_errors": [],
        "selected_tools": [],
        "tool_execution_status": "",
        "tool_results": [],
        "tool_errors": [],
        "generated_artifact": "",
        "agent_status": "",
        "next_action": "",
    }

    result = graph.invoke(initial_state)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "AES graph invocation finished: status=%s next_action=%s elapsed_ms=%.1f",
        result.get("agent_status", ""),
        result.get("next_action", ""),
        elapsed_ms,
    )
    _set_cached_result(cache_key, result)
    return result


def _result_cache_key(user_text: str) -> str:
    return hashlib.sha256(user_text.strip().encode("utf-8")).hexdigest()


def _get_cached_result(cache_key: str) -> Dict[str, Any] | None:
    now = time.monotonic()
    with _RESULT_CACHE_LOCK:
        cached = _RESULT_CACHE.get(cache_key)
        if not cached:
            return None

        created_at, result = cached
        if now - created_at > AES_RESULT_CACHE_TTL_SECONDS:
            _RESULT_CACHE.pop(cache_key, None)
            return None

        return copy.deepcopy(result)


def _set_cached_result(cache_key: str, result: Dict[str, Any]) -> None:
    now = time.monotonic()
    with _RESULT_CACHE_LOCK:
        expired_keys = [
            key
            for key, (created_at, _cached_result) in _RESULT_CACHE.items()
            if now - created_at > AES_RESULT_CACHE_TTL_SECONDS
        ]
        for key in expired_keys:
            _RESULT_CACHE.pop(key, None)

        _RESULT_CACHE[cache_key] = (now, copy.deepcopy(result))


def build_assistant_text(result: Dict[str, Any]) -> str:
    """
    Convert AES structured output into a user-facing assistant message.
    """
    generated_artifact = result.get("generated_artifact", "")
    agent_status = result.get("agent_status", "")
    next_action = result.get("next_action", "")
    missing_information = result.get("missing_information", [])
    clarification_questions = result.get("clarification_questions", [])
    validation_errors = result.get("validation_errors", [])
    numerical_recipe_errors = result.get("numerical_recipe_errors", [])
    tool_errors = result.get("tool_errors", [])

    lines: List[str] = []

    if generated_artifact:
        lines.append(generated_artifact)

    if agent_status:
        lines.append(f"\nAgent status: {agent_status}")

    if next_action:
        lines.append(f"Next action: {next_action}")

    if missing_information:
        lines.append("\nMissing information:")
        for item in missing_information:
            lines.append(f"- {item}")

    if validation_errors:
        lines.append("\nValidation errors:")
        for item in validation_errors:
            lines.append(f"- {item}")

    if numerical_recipe_errors:
        lines.append("\nNumerical recipe errors:")
        for item in numerical_recipe_errors:
            lines.append(f"- {item}")

    if clarification_questions:
        lines.append("\nClarification questions:")
        for item in clarification_questions:
            lines.append(f"- {item}")

    if tool_errors:
        lines.append("\nTool errors:")
        for item in tool_errors:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()

def build_streaming_chunk(
    completion_id: str,
    model: str,
    content: str,
) -> str:
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"

@app.get("/health")
def health():
    logger.info("Health check requested.")
    return {"status": "ok"}


@app.post("/invoke")
def invoke(query: Query):
    logger.info("Direct /invoke request received.")
    return run_aes_agent(query.text)


@app.get("/v1/models")
def list_models():
    logger.info("OpenAI-compatible model list requested.")
    return {
        "object": "list",
        "data": [
            {
                "id": AES_MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "aes",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionRequest):
    logger.info(
        "OpenAI-compatible chat completion requested: model=%s stream=%s",
        request.model,
        request.stream,
    )
    user_text = build_user_text_from_messages(request.messages)
    if not user_text:
        raise HTTPException(
            status_code=400,
            detail="No user message found in request.messages."
        )

    result = run_aes_agent(user_text)
    assistant_text = build_assistant_text(result)

    now = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"

    if request.stream:
        def event_stream():
            # First and only content chunk
            yield build_streaming_chunk(
                completion_id=completion_id,
                model=AES_MODEL_ID,
                content=assistant_text,
            )

            # Final stop chunk
            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": AES_MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
        )

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": now,
        "model": AES_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": assistant_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "aes_result": result,
    }
