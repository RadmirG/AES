from fastapi import FastAPI
from pydantic import BaseModel
import requests

app = FastAPI(title="LangGraph Service")

OLLAMA_URL = "http://ollama-server:11434/api/generate"
MODEL_NAME = "gemma4:31b"


class Query(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/invoke")
def invoke(query: Query):
    # First minimal orchestration placeholder:
    # later this becomes a real LangGraph invocation
    user_text = query.text

    prompt = f"""
You are the first orchestration layer of an engineering system.
Analyze the following problem briefly and return a structured summary.

Problem:
{user_text}
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    data = response.json()

    return {
        "raw_input": user_text,
        "model": MODEL_NAME,
        "analysis": data.get("response", "")
    }
