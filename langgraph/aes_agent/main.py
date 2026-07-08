from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Union

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from aes_agent.graph import graph

app = FastAPI(title="LangGraph Service")

AES_MODEL_ID = "aes-agent"


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


def extract_last_user_message(messages: List[ChatMessage]) -> str:
    """
    Take the last user message as the input to the AES agent.
    """
    for msg in reversed(messages):
        if msg.role == "user":
            text = extract_text_from_content(msg.content)
            if text.strip():
                return text.strip()
    return ""


def run_aes_agent(user_text: str) -> Dict[str, Any]:
    """
    Internal helper that runs the LangGraph graph.
    """
    initial_state = {
        "raw_user_input": user_text,
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

    return graph.invoke(initial_state)


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
    return {"status": "ok"}


@app.post("/invoke")
def invoke(query: Query):
    return run_aes_agent(query.text)


@app.get("/v1/models")
def list_models():
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
    user_text = extract_last_user_message(request.messages)
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
