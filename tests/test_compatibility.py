"""Basic host compatibility and launch readiness checks for Antigravity Operator."""

import shutil
import unittest
from pathlib import Path

from core.cli import check_auth_available
from core.config import list_recipes, load_recipe
from core.container import build_docker_cmd
from core.gpu import detect_gpu


class TestHostCompatibility(unittest.TestCase):
    """Smoke tests verifying host environment readiness and container launch capabilities."""

    def test_docker_available(self):
        """Verify Docker is installed or detectable on the host system."""
        docker_bin = shutil.which("docker")
        self.assertIsNotNone(docker_bin, "Docker engine binary must be installed on the host.")

    def test_recipes_loadable(self):
        """Verify recipes catalog loads and contains core processing recipes."""
        recipes_dir = Path(__file__).resolve().parent.parent / "recipes"
        recipes = list_recipes(recipes_dir)
        self.assertGreaterEqual(len(recipes), 1, "At least one recipe must be loaded.")
        recipe_names = [r.name for r in recipes]
        self.assertIn("media-link", recipe_names, "Built-in 'media-link' recipe must be available.")
        media_link = load_recipe(recipes_dir, "media-link")
        self.assertTrue(media_link.instructions_file.exists(), "Recipe instructions must exist.")

    def test_gpu_detection_runs(self):
        """Verify hardware/GPU discovery runs without errors on host."""
        gpu = detect_gpu()
        self.assertIsNotNone(gpu)
        self.assertIn(gpu.backend, ("vaapi", "nvenc", "software"))
        self.assertIn(gpu.recommended_codec, ("av1", "hevc"))

    def test_auth_check_runs(self):
        """Verify authentication discovery can inspect host environment/credentials safely."""
        has_auth, desc, eff_key = check_auth_available()
        self.assertIsInstance(has_auth, bool)
        self.assertIsInstance(desc, str)

    def test_launch_command_generation(self):
        """Verify container launch command can be constructed for a recipe."""
        recipes_dir = Path(__file__).resolve().parent.parent / "recipes"
        recipe = load_recipe(recipes_dir, "media-link")
        dummy_storage = Path("/tmp")

        cmd = build_docker_cmd(
            recipe=recipe,
            storage_root=dummy_storage,
            dry_run=True,
        )
        cmd_str = " ".join(cmd)

        self.assertIn("docker", cmd[0])
        self.assertIn("run", cmd)
        self.assertIn(":/storage:ro", cmd_str)
        self.assertIn(":/home/agent/.gemini", cmd_str)
        self.assertIn("OPERATE_DRY_RUN=1", cmd_str)


if __name__ == "__main__":
    unittest.main()
