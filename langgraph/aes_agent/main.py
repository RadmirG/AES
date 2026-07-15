from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import time
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from aes_agent.graph import graph
from aes_agent.logging_config import (
    configure_logging,
    log_content_preview,
)

configure_logging("langgraph")

app = FastAPI(title="LangGraph Service")
logger = logging.getLogger("aes_agent")

_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "AES_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    Extract the active AES request from OpenAI-style chat history.

    OpenAI-compatible clients send the full chat history. Folding all user
    turns into one problem statement can make a new deployment/log command
    inherit an older PDE request and accidentally trigger the solver workflow.

    The one safe exception is AES's own requested-output clarification. If the
    latest user turn only selects an output mode, rebuild the active request
    from the previous PDE turn plus that selected output mode.
    """
    turns = [
        {
            "role": msg.role,
            "text": extract_text_from_content(msg.content).strip(),
        }
        for msg in messages
    ]
    turns = [turn for turn in turns if turn["text"]]

    user_turn_indices = [
        index for index, turn in enumerate(turns) if turn["role"] == "user"
    ]
    if not user_turn_indices:
        return ""

    latest_user_index = user_turn_indices[-1]
    latest_user_text = turns[latest_user_index]["text"]

    if _is_requested_output_reply(latest_user_text) and _previous_assistant_asked_for_output(
        turns,
        latest_user_index,
    ):
        previous_problem = _previous_user_problem_text(turns, latest_user_index)
        requested_output = _normalize_requested_output_reply(latest_user_text)
        if previous_problem and requested_output:
            return "\n\n".join(
                [
                    previous_problem,
                    f"Requested AES output: {requested_output}",
                ]
            )

    return latest_user_text


def _previous_user_problem_text(
    turns: List[Dict[str, str]],
    before_index: int,
) -> str:
    for index in range(before_index - 1, -1, -1):
        turn = turns[index]
        if turn["role"] == "user" and _looks_like_pde_problem_text(turn["text"]):
            return turn["text"]
    return ""


def _previous_assistant_asked_for_output(
    turns: List[Dict[str, str]],
    before_index: int,
) -> bool:
    for index in range(before_index - 1, -1, -1):
        turn = turns[index]
        text = turn["text"].lower()
        if turn["role"] == "user":
            return False
        if turn["role"] != "assistant":
            continue
        if (
            "requested output is not" in text
            or "what output do you want from aes" in text
            or "select_requested_output" in text
        ):
            return True
    return False


def _is_requested_output_reply(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False

    output_markers = [
        "formulation summary",
        "summary",
        "generated dolfinx",
        "generated fenics",
        "python file",
        "fenics file",
        "dolfinx file",
        "execute",
        "execution",
        "stored result",
        "result artifacts",
        "run it",
        "compute",
        "plot",
    ]
    pde_markers = [
        "heat equation",
        "poisson",
        "-div",
        "grad",
        "dirichlet",
        "neumann",
        "boundary condition",
    ]
    return (
        len(lowered) <= 180
        and any(marker in lowered for marker in output_markers)
        and not any(marker in lowered for marker in pde_markers)
    )


def _normalize_requested_output_reply(text: str) -> str:
    lowered = text.strip().lower()
    if any(
        marker in lowered
        for marker in [
            "execute",
            "execution",
            "stored result",
            "result artifacts",
            "run it",
            "compute",
            "plot",
        ]
    ):
        return (
            "execute the generated DOLFINx/FEniCS solve and store result "
            "artifacts"
        )
    if any(
        marker in lowered
        for marker in [
            "python file",
            "fenics file",
            "dolfinx file",
            "generated dolfinx",
            "generated fenics",
            "code",
        ]
    ):
        return "generate a DOLFINx/FEniCS Python file"
    if "formulation" in lowered or "summary" in lowered:
        return "formulation summary"
    return text.strip()


def _looks_like_pde_problem_text(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "heat equation",
        "poisson",
        "laplace",
        "diffusion",
        "pde",
        "-div",
        "grad",
        "dirichlet",
        "neumann",
        "boundary condition",
        "weak form",
        "finite element",
    ]
    return any(marker in lowered for marker in markers)


def run_aes_agent(user_text: str) -> Dict[str, Any]:
    """
    Internal helper that runs the LangGraph graph.
    """
    cache_key = _result_cache_key(user_text)
    cached_result = _get_cached_result(cache_key)
    if cached_result is not None:
        logger.info(
            "AES graph invocation reused cached result: cache_key=%s",
            cache_key[:12],
        )
        return cached_result

    started_at = time.perf_counter()
    logger.info(
        "AES graph invocation started: cache_key=%s input_chars=%s",
        cache_key[:12],
        len(user_text),
    )
    log_content_preview(logger, "AES graph input", {"raw_user_input": user_text})
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
        (
            "AES graph invocation finished: status=%s next_action=%s "
            "solution_mode=%s tools=%s errors=%s elapsed_ms=%.1f"
        ),
        result.get("agent_status", ""),
        result.get("next_action", ""),
        result.get("solution_mode", ""),
        result.get("selected_tools", []),
        len(result.get("tool_errors", []) or []),
        elapsed_ms,
    )
    log_content_preview(
        logger,
        "AES graph result",
        _summarize_result_for_log(result),
    )
    _set_cached_result(cache_key, result)
    return result


def _summarize_result_for_log(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "request_intent": result.get("request_intent", ""),
        "problem_class": result.get("problem_class", ""),
        "pde_info": result.get("pde_info", ""),
        "domain_info": result.get("domain_info", ""),
        "coefficient_info": result.get("coefficient_info", ""),
        "source_info": result.get("source_info", ""),
        "bc_info": result.get("bc_info", ""),
        "initial_condition_info": result.get("initial_condition_info", ""),
        "time_info": result.get("time_info", ""),
        "solution_mode": result.get("solution_mode", ""),
        "validation_status": result.get("validation_status", ""),
        "numerical_recipe_status": result.get("numerical_recipe_status", ""),
        "selected_tools": result.get("selected_tools", []),
        "tool_execution_status": result.get("tool_execution_status", ""),
        "tool_errors": result.get("tool_errors", []),
        "agent_status": result.get("agent_status", ""),
        "next_action": result.get("next_action", ""),
    }


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
    logger.info("Direct /invoke request received: text_chars=%s", len(query.text))
    return run_aes_agent(query.text)


@app.get("/artifacts/{run_id}/{artifact_path:path}")
def get_artifact(run_id: str, artifact_path: str):
    logger.info("Artifact request received: run_id=%s path=%s", run_id, artifact_path)
    root = Path(os.getenv("AES_ARTIFACT_ROOT", "artifacts")).resolve()
    requested = (root / run_id / artifact_path).resolve()

    try:
        requested.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found.") from exc

    if not requested.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")

    return FileResponse(str(requested))


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
        (
            "OpenAI-compatible chat completion requested: model=%s stream=%s "
            "messages=%s"
        ),
        request.model,
        request.stream,
        len(request.messages),
    )
    user_text = build_user_text_from_messages(request.messages)
    if not user_text:
        raise HTTPException(
            status_code=400,
            detail="No user message found in request.messages."
        )

    result = run_aes_agent(user_text)
    assistant_text = build_assistant_text(result)
    logger.info(
        "OpenAI-compatible chat completion prepared: response_chars=%s status=%s",
        len(assistant_text),
        result.get("agent_status", ""),
    )
    log_content_preview(
        logger,
        "OpenAI-compatible chat completion response",
        {
            "assistant_text": assistant_text,
            "aes_result": _summarize_result_for_log(result),
        },
    )

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
