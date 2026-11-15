"""Unit tests for Antigravity container authentication resolution and persistence."""

import os
import unittest
from unittest.mock import patch, MagicMock

from core.cli import (
    check_auth_available,
    load_shared_credentials,
    save_shared_credentials,
    clear_shared_credentials,
    check_shared_token,
    load_volume_credentials,
    save_volume_credentials,
    clear_volume_credentials,
    check_volume_token_exists,
)


class TestAuth(unittest.TestCase):
    """Test suite for credential checking and shared ~/.gemini authentication."""

    def setUp(self):
        self.orig_gemini = os.environ.get("GEMINI_API_KEY")
        self.orig_google = os.environ.get("GOOGLE_API_KEY")
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)

    def tearDown(self):
        if self.orig_gemini is not None:
            os.environ["GEMINI_API_KEY"] = self.orig_gemini
        else:
            os.environ.pop("GEMINI_API_KEY", None)

        if self.orig_google is not None:
            os.environ["GOOGLE_API_KEY"] = self.orig_google
        else:
            os.environ.pop("GOOGLE_API_KEY", None)

    def test_auth_cli_api_key_highest_priority(self):
        with patch("core.cli.load_shared_credentials", return_value="shared-key"):
            with patch("core.cli.check_shared_token", return_value=(True, None)):
                has_auth, desc, eff_key = check_auth_available(api_key="cli-key-123")
                self.assertTrue(has_auth)
                self.assertEqual(eff_key, "cli-key-123")
                self.assertIn("CLI / environment", desc)

    def test_auth_env_api_key(self):
        os.environ["GEMINI_API_KEY"] = "env-gemini-key"
        with patch("core.cli.load_shared_credentials", return_value="shared-key"):
            has_auth, desc, eff_key = check_auth_available()
            self.assertTrue(has_auth)
            self.assertEqual(eff_key, "env-gemini-key")
            self.assertIn("CLI / environment", desc)

    def test_auth_shared_persisted_key(self):
        with patch("core.cli.load_shared_credentials", return_value="saved-shared-key"):
            with patch("core.cli.check_shared_token", return_value=(False, None)):
                has_auth, desc, eff_key = check_auth_available()
                self.assertTrue(has_auth)
                self.assertEqual(eff_key, "saved-shared-key")
                self.assertIn("shared ~/.gemini", desc)

    def test_auth_shared_oauth_token(self):
        with patch("core.cli.load_shared_credentials", return_value=None):
            with patch("core.cli.check_shared_token", return_value=(True, "user@example.com")):
                has_auth, desc, eff_key = check_auth_available()
                self.assertTrue(has_auth)
                self.assertIsNone(eff_key)
                self.assertIn("OAuth Token (user@example.com) in shared ~/.gemini", desc)

    def test_auth_none_available(self):
        with patch("core.cli.load_shared_credentials", return_value=None):
            with patch("core.cli.check_shared_token", return_value=(False, None)):
                has_auth, desc, eff_key = check_auth_available()
                self.assertFalse(has_auth)
                self.assertIsNone(eff_key)
                self.assertEqual(desc, "None")


if __name__ == "__main__":
    unittest.main()
