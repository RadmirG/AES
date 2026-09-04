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

    @patch("aes_agent.typed_problem.ollama_json")
    def test_supported_numerical_default_is_a_warning_not_a_blocker(self, model_json):
        model_json.return_value = {
            **self.model_response,
            "ambiguities": [
                "Time stepping scheme not explicitly specified; defaulted to backward_euler."
            ],
        }

        result = interpret_problem_specs(self.state)
        validated = validate_problem_specs(result)

        self.assertEqual(result["typed_spec_ambiguities"], [])
        self.assertIn(
            "non-blocking numerical default",
            result["typed_interpretation_warnings"][0],
        )
        self.assertEqual(validated["typed_validation_status"], "valid")
        self.assertTrue(validated["compilation_plan"])

    @patch("aes_agent.typed_problem.ollama_json")
    def test_explicit_time_values_override_conflicting_model_values(self, model_json):
        response = {
            **self.model_response,
            "pde_spec": {
                **self.model_response["pde_spec"],
                "time": {
                    "t0": 0.0,
                    "t_end": 1.0,
                    "dt": 0.1,
                    "scheme": "backward_euler",
                },
                "assumptions": [
                    "dt is assumed to be 0.1 because it was not specified.",
                    "Backward Euler is used as a numerical default.",
                ],
            },
        }
        model_json.return_value = response

        result = interpret_problem_specs(self.state)

        self.assertEqual(result["pde_spec"]["time"]["dt"], 0.01)
        self.assertEqual(
            result["pde_spec"]["assumptions"],
            ["Backward Euler is used as a numerical default."],
        )
        self.assertTrue(
            any(
                "preserved explicitly stated time values" in warning
                for warning in result["typed_interpretation_warnings"]
            )
        )

    @patch("aes_agent.typed_problem.ollama_json")
    def test_missing_physics_ambiguity_remains_blocking(self, model_json):
        model_json.return_value = {
            **self.model_response,
            "ambiguities": ["The boundary value is not specified."],
        }

        result = interpret_problem_specs(self.state)
        validated = validate_problem_specs(result)

        self.assertEqual(result["typed_spec_ambiguities"], ["The boundary value is not specified."])
        self.assertEqual(validated["typed_validation_status"], "invalid")
        self.assertIn("boundary value", validated["typed_validation_errors"][0].lower())

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

    @patch("aes_agent.typed_problem.ollama_json")
    def test_attached_geometry_is_authoritative_and_geometry_ambiguities_do_not_block(
        self,
        model_json,
    ):
        attached = dict(self.model_response["geometry_spec"])
        attached["metadata"] = {"id": "selected-standard-geometry"}
        attached["regions"] = [
            region for region in attached["regions"] if region["name"] != "boundary"
        ]
        model_json.return_value = {
            "pde_spec": self.model_response["pde_spec"],
            "ambiguities": [
                "The uploaded geometry file path is not provided in the current state."
            ],
        }

        result = interpret_problem_specs(
            {**self.state, "requested_geometry_spec": attached}
        )
        validated = validate_problem_specs(result)

        self.assertEqual(result["geometry_spec_source"], "request_context")
        self.assertEqual(result["geometry_spec"]["metadata"]["id"], "selected-standard-geometry")
        self.assertIn(
            "boundary",
            [region["name"] for region in result["geometry_spec"]["regions"]],
        )
        self.assertEqual(result["typed_spec_ambiguities"], [])
        self.assertTrue(
            any("Ignored model geometry ambiguity" in item for item in result["typed_interpretation_warnings"])
        )
        self.assertEqual(validated["typed_validation_status"], "valid")

    @patch("aes_agent.typed_problem.ollama_json")
    def test_invalid_attached_geometry_is_not_replaced_by_model_geometry(self, model_json):
        result = interpret_problem_specs(
            {
                **self.state,
                "requested_geometry_spec": {
                    "schema_version": "1.0",
                    "dimension": 2,
                    "source": {"kind": "mesh_file", "format": "msh"},
                },
            }
        )

        model_json.assert_not_called()
        self.assertEqual(result["geometry_spec_source"], "request_context_invalid")
        self.assertEqual(result["geometry_spec"], {})
        self.assertIn("Attached geometry is invalid", result["typed_spec_ambiguities"][0])


if __name__ == "__main__":
    unittest.main()
