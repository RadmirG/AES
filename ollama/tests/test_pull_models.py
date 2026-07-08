import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pull_models import ModelManifest, parse_manifest_text, select_models


class PullModelsManifestTests(unittest.TestCase):
    def test_parse_manifest_groups_and_default(self):
        manifest = parse_manifest_text(
            """
defaults:
  aes_ollama_model: qwen3:4b

pull_groups:
  recommended:
    description: Best local AES dev set.
    models:
      - qwen3:4b
      - qwen2.5-coder:3b

  slow_optional:
    description: Slower checks.
    models:
      - qwen3:8b

models:
  default: should-not-override-defaults
"""
        )

        self.assertEqual(manifest.default_model, "qwen3:4b")
        self.assertEqual(manifest.pull_groups["recommended"], ["qwen3:4b", "qwen2.5-coder:3b"])
        self.assertEqual(manifest.pull_groups["slow_optional"], ["qwen3:8b"])

    def test_parse_manifest_falls_back_to_models_default(self):
        manifest = parse_manifest_text(
            """
models:
  default: gemma4:e4b
"""
        )

        self.assertEqual(manifest.default_model, "gemma4:e4b")

    def test_select_models_deduplicates_in_order(self):
        manifest = ModelManifest(
            default_model="qwen3:4b",
            pull_groups={"recommended": ["qwen3:4b", "phi4-mini:3.8b"]},
        )

        selected = select_models(
            manifest=manifest,
            groups=["recommended"],
            include_default=True,
            explicit_models=["phi4-mini:3.8b", "llama3.2:3b"],
        )

        self.assertEqual(selected, ["qwen3:4b", "phi4-mini:3.8b", "llama3.2:3b"])

    def test_select_models_rejects_unknown_group(self):
        manifest = ModelManifest(default_model=None, pull_groups={"recommended": []})

        with self.assertRaisesRegex(ValueError, "unknown pull group"):
            select_models(manifest, groups=["missing"], include_default=False, explicit_models=[])


if __name__ == "__main__":
    unittest.main()
