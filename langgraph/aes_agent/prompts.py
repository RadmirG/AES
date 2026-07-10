from __future__ import annotations

import json
from typing import Any, Dict, List


def detect_request_intent_prompt(user_text: str) -> str:
    return f"""
You are the first routing node in an agentic engineering system named AES.

Task:
Decide whether the latest user message is a numerical engineering/PDE solve
request that should enter the AES solver workflow.

Return ONLY a valid JSON object with exactly these keys:
{{
  "request_intent": "...",
  "intent_reason": "..."
}}

Rules:
- "request_intent" must be one of:
  "engineering_pde_request",
  "operational_command",
  "general_question",
  "unsupported_request",
  "empty_request"
- Use "engineering_pde_request" only when the user asks AES to formulate,
  solve, simulate, or compute an engineering/mathematical PDE problem.
- Use "operational_command" for shell commands, Docker commands, SSH commands,
  curl commands, deployment commands, log commands, or server maintenance.
- Use "general_question" for conceptual questions about AES, LangGraph, MCP,
  Ollama, architecture, or documentation.
- Use "unsupported_request" when the message is neither an engineering PDE
  solve request nor a supported AES task.
- "intent_reason" must be one concise sentence.

Latest user message:
{user_text}
"""


def classify_problem_prompt(user_text: str) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Classify the following engineering/mathematical problem.

Return ONLY a valid JSON object with exactly these keys:
{{
  "problem_class": "...",
  "pde_info": "..."
}}

Rules:
- "problem_class" should be one of:
  "forward_problem", "inverse_problem", "optimization_problem", "unknown_problem"
- "pde_info" should be a short label such as:
  "stationary_diffusion_equation",
  "time_dependent_heat_equation",
  "unknown_pde"

Problem:
{user_text}
"""


def extract_mathematical_structure_prompt(
    user_text: str,
    problem_class: str,
    pde_info: str,
) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Extract the mathematical structure of the problem.

Current known state:
- problem_class: {problem_class}
- pde_info: {pde_info}

Return ONLY a valid JSON object with exactly these keys:
{{
  "domain_info": "...",
  "coefficient_info": "...",
  "source_info": "...",
  "bc_info": "...",
  "initial_condition_info": "...",
  "time_info": "..."
}}

Guidelines:
- "domain_info" should be a short label such as:
  "cube_domain", "rectangular_domain", "domain_symbolically_specified", "unknown_domain"
- "coefficient_info" should be a short label such as:
  "spatially_dependent_coefficient_given",
  "constant_coefficient_given",
  "unknown_coefficient"
- "source_info" should contain the source/right-hand-side expression if it is
  explicitly given, otherwise "unknown_source".
- "bc_info" should be a short label such as:
  "dirichlet_boundary_condition",
  "neumann_boundary_condition",
  "robin_boundary_condition",
  "unknown_boundary_condition"
- "initial_condition_info" should contain the initial-condition expression for
  time-dependent problems if explicitly given, otherwise "unknown_initial_condition".
- "time_info" should summarize time interval and time step if explicitly given,
  otherwise "unknown_time".

Problem:
{user_text}
"""


def check_problem_completeness_prompt(
    user_text: str,
    snapshot: Dict[str, Any],
) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Check whether the following PDE problem description is sufficiently specified
for a next engineering step, and identify missing or inconsistent information.

Current extracted state:
{json.dumps(snapshot, indent=2)}

Return ONLY a valid JSON object with exactly this key:
{{
  "missing_information": ["...", "..."]
}}

Rules:
- Return a JSON list of strings.
- If nothing is obviously missing, return an empty list.
- Flag inconsistencies, for example:
  - stationary PDE but time-dependent source term,
  - unclear boundary conditions,
  - unclear domain geometry,
  - unclear coefficient information,
  - for time-dependent problems, missing initial condition or time interval.

Problem:
{user_text}
"""


def generate_clarification_prompt(snapshot: Dict[str, Any]) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Generate concise questions that resolve the missing information or validation
errors in the current PDE problem.

Current state:
{json.dumps(snapshot, indent=2)}

Return ONLY a valid JSON object with exactly these keys:
{{
  "clarification_questions": ["...", "..."],
  "generated_artifact": "..."
}}

Rules:
- Ask one actionable question for each distinct unresolved issue.
- Do not ask for information already present in the state.
- "generated_artifact" must briefly explain why clarification is required and
  list the questions in a user-facing form.
"""


def select_formulation_prompt(snapshot: Dict[str, Any]) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Select the next mathematical formulation step.

Current extracted state:
{json.dumps(snapshot, indent=2)}

Return ONLY a valid JSON object with exactly this key:
{{
  "selected_formulation": "..."
}}

Rules:
- If missing_information is non-empty, return "clarification_required".
- Otherwise choose a short label such as:
  "weak_formulation_candidate",
  "strong_formulation_summary",
  "fem_problem_setup",
  "unknown_formulation"
"""


def validate_formulation_prompt(snapshot: Dict[str, Any]) -> str:
    return f"""
You are a mathematical validation node in an agentic engineering system.

Task:
Validate whether the selected formulation is compatible with the extracted PDE
problem and sufficiently specified for tool selection.

Current state:
{json.dumps(snapshot, indent=2)}

Return ONLY a valid JSON object with exactly these keys:
{{
  "validation_status": "valid",
  "validation_errors": []
}}

Rules:
- "validation_status" must be either "valid" or "invalid".
- Return "invalid" when the formulation contradicts the PDE type, domain,
  coefficients, or boundary conditions.
- Return "invalid" when the selected formulation is unknown or still requires
  clarification.
- Describe each concrete problem in "validation_errors".
- For a valid formulation, return an empty "validation_errors" list.
"""


def select_tools_prompt(
    snapshot: Dict[str, Any],
    available_tools: List[Dict[str, Any]],
) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Select the next tools to be used.

Current extracted state:
{json.dumps(snapshot, indent=2)}

Available tools:
{json.dumps(available_tools, indent=2)}

Return ONLY a valid JSON object with exactly this key:
{{
  "selected_tools": ["...", "..."]
}}

Rules:
- Return a JSON list of short tool labels.
- Select only tool names from the available-tools catalog.
- Select the smallest useful set for the next engineering step.
"""


def generate_fenics_dolfinx_code_prompt(snapshot: Dict[str, Any]) -> str:
    return f"""
You are a senior numerical software engineer inside AES.

Task:
Generate one executable Python script for DOLFINx/FEniCSx that implements the
PDE problem described by the current AES state.

Current AES state:
{json.dumps(snapshot, indent=2)}

Return ONLY a valid JSON object with exactly these keys:
{{
  "summary": "...",
  "python_code": "...",
  "expected_artifacts": ["solution.xdmf", "diagnostics.json"]
}}

Code requirements:
- Use DOLFINx/FEniCSx, not legacy dolfin/fenics.
- The script must be self-contained and runnable as `python solve.py` inside a
  DOLFINx container.
- Prefer imports from: dolfinx, ufl, mpi4py, petsc4py, numpy, matplotlib,
  pathlib, json, math.
- Do not use network access, shell commands, subprocesses, dynamic imports,
  eval, exec, input, or absolute output paths.
- Write outputs into the current working directory only.
- Use clear variable names and comments where useful.
- Include basic diagnostics printed to stdout and, if practical, write
  diagnostics.json.
- If plotting is included, save a PNG file instead of opening a GUI window.
- Keep the code robust for headless container execution.
"""


def generate_artifact_prompt(snapshot: Dict[str, Any]) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Generate a compact structured engineering artifact.

Current extracted state:
{json.dumps(snapshot, indent=2)}

Return ONLY a valid JSON object with exactly this key:
{{
  "generated_artifact": "..."
}}

Rules:
- If clarification is required, produce a short clarification summary.
- Otherwise produce a short engineering summary suitable for the next workflow step.
- Keep it concise but informative.
"""
