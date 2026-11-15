"""Unit tests for Docker container command generator and network isolation."""

import unittest
from pathlib import Path

from core.config import RecipeConfig
from core.container import build_docker_cmd, IMAGE_NAME


class TestContainer(unittest.TestCase):
    """Test suite for Docker runner command construction."""

    def setUp(self):
        self.recipe = RecipeConfig(
            name="media-link",
            version="1.0.0",
            description="Test recipe",
            timeout="1h",
            network_default=True,
            gpu_default=False,
            resources={"pids": 1024, "memory": "4g", "cpus": 2},
            path=Path("/tmp/recipes/media-link/config.json"),
            instructions_file=Path("/tmp/recipes/media-link/INSTRUCTIONS.md"),
        )
        self.storage_root = Path("/tmp/storage")

    def test_default_network_and_dns(self):
        cmd = build_docker_cmd(
            recipe=self.recipe,
            storage_root=self.storage_root,
            offline=False,
            enable_metadata=True,
        )
        cmd_str = " ".join(cmd)
        self.assertIn("--dns=9.9.9.9", cmd_str)
        self.assertIn("--dns=149.112.112.112", cmd_str)
        self.assertNotIn("--network=none", cmd_str)
        self.assertIn("OPERATE_OFFLINE=0", cmd_str)
        self.assertIn("OPERATE_METADATA=1", cmd_str)
        self.assertIn(IMAGE_NAME, cmd)

    def test_offline_mode_network_none(self):
        cmd = build_docker_cmd(
            recipe=self.recipe,
            storage_root=self.storage_root,
            offline=True,
            enable_metadata=False,
        )
        cmd_str = " ".join(cmd)
        self.assertIn("--network=none", cmd_str)
        self.assertNotIn("--dns=", cmd_str)
        self.assertIn("OPERATE_OFFLINE=1", cmd_str)
        self.assertIn("OPERATE_METADATA=0", cmd_str)


if __name__ == "__main__":
    unittest.main()
