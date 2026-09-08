import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aes_agent import nodes
from aes_agent.specs.legacy import build_legacy_specs
from aes_agent.typed_problem import interpret_problem_specs, validate_problem_specs


REQUEST = (
    "Solve the transient heat equation on the attached 3D Stepped mounting bracket. "
    "Use alpha=xy/10, f=0, Use initial condition u(x,y,0)=sin(pi*x)sin(pi*y) "
    "on base_bottom, final time T=1, and dt=0.001. Execute and store all result artifacts."
)


def bracket_state(prompt=REQUEST):
    path = Path(__file__).resolve().parents[2] / "examples/geometries/stepped-bracket-solid-3d/geometry.json"
    classification = nodes._classify_problem_from_text(prompt)
    return {
        "raw_user_input": prompt,
        **classification,
        **nodes._extract_structure_from_text(prompt, classification["pde_info"]),
        "requested_geometry_spec": json.loads(path.read_text(encoding="utf-8")),
    }


def test_bracket_expression_does_not_include_its_face_qualifier():
    state = bracket_state()
    assert state["initial_condition_info"] == "sin(pi*x)*sin(pi*y)"
    assert state["bc_info"] == "unknown_boundary_condition"
    pde, _ = build_legacy_specs(state)
    assert pde.initial_condition.value.value == "sin(pi*x)*sin(pi*y)"
    assert pde.equation.diffusion.value == "x*y/10"
    assert pde.time.dt == 0.001


@pytest.mark.parametrize("mode", ["llm_first", "deterministic_only", "model_unavailable"])
def test_bracket_clarifies_scope_without_losing_attached_geometry(monkeypatch, mode):
    state = bracket_state()
    # Even a conflicting earlier model summary must not erase raw symbolic physics.
    state["coefficient_info"] = "1"
    state["initial_condition_info"] = "20"
    pde, _ = build_legacy_specs(state)
    candidate = pde.model_dump(mode="json")
    candidate["spatial_dimension"] = 1
    candidate["initial_condition"] = None
    candidate["equation"]["diffusion"]["value"] = "1"
    candidate["equation"]["diffusion"]["kind"] = "constant"
    monkeypatch.setenv("AES_TYPED_INTERPRETATION_MODE", mode if mode == "deterministic_only" else "llm_first")
    response = {} if mode == "model_unavailable" else {
        "pde_spec": candidate,
        "ambiguities": ["domain_geometry_specification", "dimension_consistency_check_for_initial_condition"],
    }
    with patch("aes_agent.typed_problem.ollama_json", return_value=response):
        state.update(interpret_problem_specs(state))
    state.update(validate_problem_specs(state))
    with patch.object(nodes, "ollama_json", side_effect=AssertionError("Do not recheck without geometry")):
        state.update(nodes.check_problem_completeness(state))
        clarification = nodes.generate_clarification(state)
    assert state["geometry_spec"]["metadata"]["id"] == "stepped-bracket-solid-3d"
    assert state["pde_spec"]["spatial_dimension"] == 3
    assert state["pde_spec"]["equation"]["diffusion"]["value"] == "x*y/10"
    assert state["typed_validation_status"] == "invalid"
    errors = " ".join(state["missing_information"])
    assert "base_bottom" in errors and "throughout" in errors
    assert "boundary condition" in errors.lower()
    assert "syntax" not in errors
    assert "domain_geometry" not in errors
    assert "unit square" not in errors
    assert "dimension_consistency" not in errors
    assert clarification["agent_status"] == "needs_clarification"


@pytest.mark.parametrize("coefficient,status", [("xy/10", "unsupported"), ("0.01", "ready")])
def test_complete_bracket_request_preserves_physics_and_reports_capability(monkeypatch, coefficient, status):
    prompt = (
        "Solve the transient heat equation on the attached 3D bracket. "
        f"Use alpha={coefficient}, f=0, u=100 on base_bottom. "
        "Use initial condition u(x,y,z,0)=sin(pi*x)sin(pi*y) throughout the volume. "
        "Use final time T=1 and dt=0.001. Execute and store artifacts."
    )
    state = bracket_state(prompt)
    pde, _ = build_legacy_specs(state)
    monkeypatch.setenv("AES_TYPED_INTERPRETATION_MODE", "llm_first")
    with patch("aes_agent.typed_problem.ollama_json", return_value={"pde_spec": pde.model_dump(mode="json")}):
        state.update(interpret_problem_specs(state))
    state.update(validate_problem_specs(state))
    assert state["typed_validation_status"] == "valid", state["typed_validation_errors"]
    assert state["compilation_plan"]["status"] == status
    assert state["pde_spec"]["boundary_conditions"][0]["region"] == "base_bottom"
    assert state["pde_spec"]["boundary_conditions"][0]["value"]["value"] == "100"
    assert state["pde_spec"]["time"]["dt"] == 0.001
    assert nodes.check_problem_completeness(state)["missing_information"] == []
    if status == "unsupported":
        assert "constant diffusion" in " ".join(state["compilation_plan"]["capability_errors"])


def test_invalid_typed_problem_does_not_reenter_legacy_completeness():
    state = bracket_state()
    state.update(typed_validation_status="invalid", typed_validation_errors=["The initial condition has an unknown symbol."])
    with patch.object(nodes, "ollama_json", side_effect=AssertionError("Do not recheck without geometry")):
        result = nodes.check_problem_completeness(state)
    assert result["missing_information"] == state["typed_validation_errors"]


@pytest.mark.parametrize("expression", ["0.25", "1e-3", "1+x*y/10", "sin(pi*x)*sin(pi*y)"])
def test_parameter_expressions_are_not_truncated_to_numeric_prefixes(expression):
    state = bracket_state(REQUEST.replace("alpha=xy/10", f"alpha={expression}"))
    state["coefficient_info"] = "1"
    pde, _ = build_legacy_specs(state)
    assert pde.equation.diffusion.value == expression


@pytest.mark.parametrize("value", ["0.25", "1e-3", "sin(pi*x)sin(pi*y)"])
@pytest.mark.parametrize("scope", ["on base_bottom", "throughout the volume", ""])
def test_initial_clause_preserves_decimals_and_scope(value, scope):
    from aes_agent.specs.request_evidence import initial_condition_clauses, without_initial_conditions

    prompt = f"Use initial temperature u={value} {scope}, final time T=1 and dt=0.001."
    clauses = initial_condition_clauses(prompt)
    assert len(clauses) == 1
    assert clauses[0].expression == value
    assert clauses[0].scope == scope.removeprefix("on ").removeprefix("throughout ")
    assert "initial" not in without_initial_conditions(prompt)
    assert "T=1" in without_initial_conditions(prompt)
