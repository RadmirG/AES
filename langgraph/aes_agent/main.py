from fastapi import FastAPI
from pydantic import BaseModel

from aes_agent.graph import graph

app = FastAPI(title="LangGraph Service")


class Query(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/invoke")
def invoke(query: Query) -> dict:
    initial_state = {
        "raw_user_input": query.text,
        "problem_class": "",
        "domain_info": "",
        "pde_info": "",
        "coefficient_info": "",
        "bc_info": "",
        "missing_information": [],
        "selected_formulation": "",
        "selected_tools": [],
        "generated_artifact": "",
    }

    result = graph.invoke(initial_state)
    return result