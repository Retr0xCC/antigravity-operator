"""Host compatibility and plan engine test suite for Antigravity Media Operator."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.cli import cmd_doctor
from core.gpu import detect_gpu
from core.launcher import build_host_profile, resolve_kit_path
from core.plan import execute_plan, load_plan, validate_plan, PlanError


class TestHostCompatibility(unittest.TestCase):
    """Test suite verifying host environment readiness, kit resolution, and plan safety."""

    def test_gpu_detection(self):
        """Verify hardware/GPU discovery runs without errors on host."""
        gpu = detect_gpu()
        self.assertIsNotNone(gpu)
        self.assertIn(gpu.backend, ("vaapi", "nvenc", "software"))
        self.assertIn(gpu.recommended_codec, ("av1", "hevc"))
        d = gpu.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("supports_av1", d)
        self.assertIn("recommended_encoder", d)

    def test_host_profile_generation(self):
        """Verify host_profile.json context is properly generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "Downloads" / "TestSeries"
            dst = Path(tmpdir) / "Media" / "TV"
            src.mkdir(parents=True)
            dst.mkdir(parents=True)

            profile = build_host_profile(
                source_dir=src,
                dest_dir=dst,
                mode="compress",
                quality=26,
            )

            self.assertEqual(profile["host_input_path"], str(src.resolve()))
            self.assertEqual(profile["host_output_path"], str(dst.resolve()))
            self.assertEqual(profile["mode"], "compress")
            self.assertEqual(profile["quality"], 26)
            self.assertIn("gpu", profile)
            self.assertIn("backend", profile["gpu"])

    def test_plan_validation_and_dry_run(self):
        """Verify plan validation and safe simulation of actions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            src_file = tmp_path / "ep01.mkv"
            src_file.write_text("dummy media content")
            target_dir = tmp_path / "TV" / "Show (2024)" / "Season 01"
            dst_file = target_dir / "Show S01E01.mkv"

            plan_data = {
                "version": "1.0",
                "category": "tv",
                "title": "Show",
                "year": 2024,
                "actions": [
                    {"type": "mkdir", "path": str(target_dir)},
                    {"type": "link", "src": str(src_file), "dst": str(dst_file)},
                ],
            }

            errors = validate_plan(plan_data)
            self.assertEqual(errors, [])

            plan_file = tmp_path / "plan.json"
            plan_file.write_text(json.dumps(plan_data))

            # Dry-run execution must succeed and NOT create destination files
            ok = execute_plan(plan_file, dry_run=True)
            self.assertTrue(ok)
            self.assertFalse(dst_file.exists())

            # Real execution must create hardlink
            ok_real = execute_plan(plan_file, dry_run=False)
            self.assertTrue(ok_real)
            self.assertTrue(dst_file.exists())
            self.assertEqual(src_file.stat().st_ino, dst_file.stat().st_ino)

    def test_plan_validation_rejects_malformed_actions(self):
        """Verify invalid action types or missing paths are caught by validator."""
        invalid_data = {
            "version": "1.0",
            "actions": [
                {"type": "invalid_action"},
                {"type": "link", "src": "/path/to/src"},  # missing dst
            ],
        }
        errs = validate_plan(invalid_data)
        self.assertGreaterEqual(len(errs), 2)

    def test_kit_resolution_and_spec(self):
        """Verify media-operator kit resolution (local directory or remote OCI reference)."""
        kit_path_str = resolve_kit_path()
        kit_path = Path(kit_path_str)

        if kit_path.is_dir():
            self.assertTrue((kit_path / "spec.yaml").is_file(), "spec.yaml must be present in kit")
            self.assertTrue((kit_path / "AGENTS.md").is_file(), "AGENTS.md must be present in kit")
            self.assertTrue((kit_path / "Dockerfile").is_file(), "Dockerfile must be present in kit")

            spec_content = (kit_path / "spec.yaml").read_text()
            self.assertIn("kind: mixin", spec_content)
            self.assertIn("displayName: Media Pipeline & Library Operator", spec_content)
            self.assertNotIn("name: media-operator", spec_content, "schemaVersion 3 mixin descriptors do not have a 'name' field")
            self.assertNotIn("imdb-api.com", spec_content, "imdb-api.com should be removed")
            self.assertIn("api.themoviedb.org", spec_content)
        else:
            self.assertEqual(kit_path_str, "ghcr.io/retr0xcc/media-operator-kit:latest")

        # Verify operator master AGENTS.md
        master_agents = Path(__file__).resolve().parent.parent / "core" / "AGENTS.md"
        self.assertTrue(master_agents.is_file(), "core/AGENTS.md must exist in operator repo")
        content = master_agents.read_text(encoding="utf-8")
        self.assertIn("IMDb", content)
        self.assertIn("site:imdb.com", content)


if __name__ == "__main__":
    unittest.main()
