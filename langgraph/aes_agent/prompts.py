from __future__ import annotations

import json
from typing import Any, Dict


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
  "bc_info": "..."
}}

Guidelines:
- "domain_info" should be a short label such as:
  "cube_domain", "rectangular_domain", "domain_symbolically_specified", "unknown_domain"
- "coefficient_info" should be a short label such as:
  "spatially_dependent_coefficient_given",
  "constant_coefficient_given",
  "unknown_coefficient"
- "bc_info" should be a short label such as:
  "dirichlet_boundary_condition",
  "neumann_boundary_condition",
  "robin_boundary_condition",
  "unknown_boundary_condition"

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
  - unclear coefficient information.

Problem:
{user_text}
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


def select_tools_prompt(snapshot: Dict[str, Any]) -> str:
    return f"""
You are an orchestration node in an agentic engineering system.

Task:
Select the next tools to be used.

Current extracted state:
{json.dumps(snapshot, indent=2)}

Return ONLY a valid JSON object with exactly this key:
{{
  "selected_tools": ["...", "..."]
}}

Rules:
- Return a JSON list of short tool labels.
- If clarification is required, return ["clarification_tool"].
- Otherwise possible labels include:
  "pde_parser",
  "formulation_selector",
  "weak_form_builder",
  "mesh_generator",
  "fenics_codegen",
  "solver_config_builder",
  "validation_tool"
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