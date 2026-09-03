from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from aes_agent.specs.legacy import build_legacy_specs
from aes_agent.typed_problem import interpret_problem_specs, validate_problem_specs


class TypedProblemInterpretationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "raw_user_input": (
                "Solve the transient heat equation on the unit square Omega=[0,1]^2. "
                "Use du/dt = alpha * Delta(u) + f with alpha=1 and f=1. "
                "Use u=0 on the boundary. Use initial condition "
                "u(x,y,0)=sin(pi*x)*sin(pi*y). Use T=1 and dt=0.01."
            ),
            "problem_class": "forward_problem",
            "pde_info": "time_dependent_heat_equation",
            "domain_info": "unit_square",
            "coefficient_info": "1",
            "source_info": "1",
            "bc_info": "dirichlet_boundary_condition",
            "initial_condition_info": "sin(pi*x)*sin(pi*y)",
            "time_info": "T=1, dt=0.01",
        }
        pde, geometry = build_legacy_specs(self.state)
        assert pde is not None and geometry is not None
        self.model_response = {
            "pde_spec": pde.model_dump(mode="json"),
            "geometry_spec": geometry.model_dump(mode="json"),
            "ambiguities": [],
        }

    @patch("aes_agent.typed_problem.ollama_json")
    def test_supported_heat_problem_calls_llm_before_compatibility_parser(self, model_json):
        model_json.return_value = self.model_response

        with patch.dict(os.environ, {"AES_TYPED_INTERPRETATION_MODE": "llm_first"}):
            result = interpret_problem_specs(self.state)

        model_json.assert_called_once()
        self.assertIn("schema", model_json.call_args.kwargs)
        self.assertEqual(result["typed_spec_source"], "llm_structured_extraction")
        self.assertEqual(result["typed_interpretation_warnings"], [])

    @patch("aes_agent.typed_problem.ollama_json", return_value={})
    def test_invalid_llm_response_uses_explicit_deterministic_fallback(self, model_json):
        with patch.dict(os.environ, {"AES_TYPED_INTERPRETATION_MODE": "llm_first"}):
            result = interpret_problem_specs(self.state)
            validated = validate_problem_specs(result)

        model_json.assert_called_once()
        self.assertEqual(result["typed_spec_source"], "deterministic_fallback")
        self.assertTrue(result["typed_interpretation_warnings"])
        self.assertEqual(validated["typed_validation_status"], "valid")
        self.assertTrue(validated["typed_validation_warnings"])

    @patch(
        "aes_agent.typed_problem.ollama_json",
        side_effect=AssertionError("deterministic-only mode must not call the model"),
    )
    def test_deterministic_only_mode_is_explicit(self, _model_json):
        with patch.dict(os.environ, {"AES_TYPED_INTERPRETATION_MODE": "deterministic_only"}):
            result = interpret_problem_specs(self.state)

        self.assertEqual(result["typed_spec_source"], "deterministic_configuration")


if __name__ == "__main__":
    unittest.main()
