from __future__ import annotations

import unittest
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - test environment dependency guard
    yaml = None


MCP_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(yaml is None, "PyYAML is not installed.")
class ProviderManifestTests(unittest.TestCase):
    def test_provider_index_points_to_existing_manifests(self):
        index = yaml.safe_load((MCP_ROOT / "providers.yaml").read_text())
        providers = index["providers"]

        self.assertGreaterEqual(len(providers), 3)
        for provider in providers:
            manifest_path = MCP_ROOT / provider["manifest"]
            self.assertTrue(
                manifest_path.exists(),
                f"Missing provider manifest: {manifest_path}",
            )

            manifest = yaml.safe_load(manifest_path.read_text())
            self.assertEqual(manifest["id"], provider["id"])

            compose_path = manifest_path.parent / manifest["compose_file"]
            allowlist_path = manifest_path.parent / manifest["allowlist"]
            self.assertTrue(compose_path.exists())
            self.assertTrue(allowlist_path.exists())


if __name__ == "__main__":
    unittest.main()
