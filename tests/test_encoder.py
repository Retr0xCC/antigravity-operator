"""Unit tests for Muxpress multi-backend encoder."""

import unittest
from pathlib import Path

from recipes.tools.muxpress.models import EncoderSettings
from recipes.tools.muxpress.encoder import (
    build_vaapi_command,
    build_nvenc_command,
    build_software_command,
    build_encode_command,
)


class TestEncoder(unittest.TestCase):
    """Test suite for FFmpeg command construction."""

    def test_settings_backward_compatibility(self):
        s = EncoderSettings(preset="p5", qp=30, force_hevc=True)
        self.assertEqual(s.quality, 30)
        self.assertTrue(s.force_reencode)

        s2 = EncoderSettings(quality=24, force_reencode=True)
        self.assertEqual(s2.qp, 24)
        self.assertTrue(s2.force_hevc)

    def test_vaapi_av1_command_structure(self):
        settings = EncoderSettings(
            backend="vaapi",
            codec="av1",
            quality=26,
            device="/dev/dri/renderD128",
        )
        cmd = build_vaapi_command(Path("input.mkv"), Path("output.temp.mkv"), settings)
        cmd_str = " ".join(cmd)

        self.assertIn("-vaapi_device /dev/dri/renderD128", cmd_str)
        self.assertIn("-c:v:0 av1_vaapi", cmd_str)
        self.assertIn("-rc_mode CQP", cmd_str)
        self.assertIn("-global_quality 26", cmd_str)
        self.assertIn("-vf format=nv12|p010,hwupload", cmd_str)
        self.assertEqual(cmd[-1], "output.temp.mkv")

    def test_vaapi_hevc_command_structure(self):
        settings = EncoderSettings(
            backend="vaapi",
            codec="hevc",
            quality=28,
            device="/dev/dri/renderD128",
        )
        cmd = build_vaapi_command(Path("input.mkv"), Path("output.temp.mkv"), settings)
        cmd_str = " ".join(cmd)

        self.assertIn("-c:v:0 hevc_vaapi", cmd_str)
        self.assertIn("-global_quality 28", cmd_str)

    def test_nvenc_command_structure(self):
        settings = EncoderSettings(
            backend="nvenc",
            codec="hevc",
            quality=28,
            preset="p6",
        )
        cmd = build_nvenc_command(Path("input.mkv"), Path("output.temp.mkv"), settings)
        cmd_str = " ".join(cmd)

        self.assertIn("-hwaccel cuda", cmd_str)
        self.assertIn("-c:v:0 hevc_nvenc", cmd_str)
        self.assertIn("-preset p6", cmd_str)
        self.assertIn("-qp 28", cmd_str)

    def test_software_svtav1_command(self):
        settings = EncoderSettings(
            backend="software",
            codec="av1",
            quality=28,
        )
        cmd = build_software_command(Path("input.mkv"), Path("output.temp.mkv"), settings)
        cmd_str = " ".join(cmd)

        self.assertIn("-c:v:0 libsvtav1", cmd_str)
        self.assertIn("-crf 28", cmd_str)


if __name__ == "__main__":
    unittest.main()
