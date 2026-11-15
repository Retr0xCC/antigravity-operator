"""Unit tests for GPU and hardware detection."""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from core.gpu import (
    GPUInfo,
    detect_gpu,
    VENDOR_AMD,
    VENDOR_NVIDIA,
    VENDOR_INTEL,
)


class TestGPU(unittest.TestCase):
    """Test suite for hardware discovery and codec recommendation."""

    @patch("core.gpu._find_render_node", return_value="/dev/dri/renderD128")
    @patch("core.gpu._read_sysfs_pci_gpus")
    @patch("core.gpu._detect_via_lspci")
    def test_amd_rx7700xt_detection(self, mock_lspci, mock_sysfs, mock_render):
        # Simulate AMD RX 7700 XT (RDNA 3 Navi 32, vendor 0x1002, device 0x747e)
        mock_sysfs.return_value = [{
            "pci_id": "0000:03:00.0",
            "vendor": VENDOR_AMD,
            "device_id": "0x747e",
            "name": "Navi 32 [Radeon RX 7700 XT / 7800 XT]",
        }]
        mock_lspci.return_value = [{
            "raw": "03:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7700 XT] [1002:747e]",
            "vendor": VENDOR_AMD,
        }]

        gpu = detect_gpu()
        self.assertEqual(gpu.vendor, "amd")
        self.assertTrue(gpu.is_hardware)
        self.assertTrue(gpu.supports_av1)
        self.assertEqual(gpu.recommended_codec, "av1")
        self.assertEqual(gpu.recommended_encoder, "av1_vaapi")
        self.assertEqual(gpu.backend, "vaapi")
        self.assertEqual(gpu.device_path, "/dev/dri/renderD128")

    @patch("core.gpu._find_render_node", return_value=None)
    @patch("core.gpu._read_sysfs_pci_gpus", return_value=[])
    @patch("core.gpu._detect_via_lspci", return_value=[])
    @patch("shutil.which")
    @patch("subprocess.run")
    def test_nvidia_detection(self, mock_subproc, mock_which, mock_lspci, mock_sysfs, mock_render):
        # Simulate NVIDIA RTX 4080 (Ada Lovelace, supports AV1 NVENC)
        mock_which.side_effect = lambda cmd: "/usr/bin/nvidia-smi" if cmd == "nvidia-smi" else None
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "NVIDIA GeForce RTX 4080, 550.54.14\n"
        mock_subproc.return_value = mock_res

        gpu = detect_gpu()
        self.assertEqual(gpu.vendor, "nvidia")
        self.assertTrue(gpu.is_hardware)
        self.assertTrue(gpu.supports_av1)
        self.assertEqual(gpu.recommended_codec, "av1")
        self.assertEqual(gpu.recommended_encoder, "av1_nvenc")
        self.assertEqual(gpu.backend, "nvenc")

    @patch("core.gpu._find_render_node", return_value=None)
    @patch("core.gpu._read_sysfs_pci_gpus", return_value=[])
    @patch("core.gpu._detect_via_lspci", return_value=[])
    @patch("shutil.which", return_value=None)
    def test_cpu_software_fallback(self, mock_which, mock_lspci, mock_sysfs, mock_render):
        gpu = detect_gpu()
        self.assertEqual(gpu.vendor, "software")
        self.assertFalse(gpu.is_hardware)
        self.assertEqual(gpu.backend, "software")
        self.assertEqual(gpu.recommended_encoder, "libx265")


if __name__ == "__main__":
    unittest.main()
