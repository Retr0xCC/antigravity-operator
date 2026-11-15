"""Hardware and GPU autodetection for media transcoding.

Supports AMD (Radeon RX 7000 / RDNA 3 AV1 & HEVC via VA-API),
NVIDIA (NVENC HEVC & AV1 via CUDA), Intel (QSV/VA-API), and CPU fallback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# Known PCI vendor IDs
VENDOR_AMD = "0x1002"
VENDOR_NVIDIA = "0x10de"
VENDOR_INTEL = "0x8086"


@dataclass
class GPUInfo:
    """Detected hardware accelerator capabilities."""

    vendor: str  # "amd", "nvidia", "intel", "software"
    name: str  # Friendly name e.g. "AMD Radeon RX 7700 XT"
    device_path: str | None = None  # e.g. "/dev/dri/renderD128"
    supported_codecs: list[str] = field(default_factory=lambda: ["hevc", "h264"])
    recommended_codec: str = "hevc"  # "av1", "hevc", "h264"
    recommended_encoder: str = "hevc_vaapi"
    backend: str = "vaapi"  # "vaapi", "nvenc", "qsv", "software"
    is_hardware: bool = True
    driver_version: str | None = None

    @property
    def supports_av1(self) -> bool:
        """True if the hardware encoder supports AV1."""
        return "av1" in self.supported_codecs


def _check_vainfo_av1_encode() -> bool:
    """Check if vainfo reports VAEntrypointEncSlice for AV1."""
    vainfo = shutil.which("vainfo")
    if not vainfo:
        return False
    try:
        res = subprocess.run([vainfo], capture_output=True, text=True, timeout=3)
        out = res.stdout + res.stderr
        for line in out.splitlines():
            if "VAProfileAV1" in line and "VAEntrypointEncSlice" in line:
                return True
    except Exception:
        pass
    return False


def _read_sysfs_pci_gpus() -> list[dict[str, str]]:
    """Scan /sys/bus/pci/devices for display controllers (class 0x03xxxx)."""
    gpus: list[dict[str, str]] = []
    pci_dir = Path("/sys/bus/pci/devices")
    if not pci_dir.is_dir():
        return gpus

    for dev in pci_dir.iterdir():
        try:
            class_file = dev / "class"
            if not class_file.is_file():
                continue
            pci_class = class_file.read_text().strip().lower()
            # Display controllers have class starting with 0x03
            if not pci_class.startswith("0x03"):
                continue

            vendor = (dev / "vendor").read_text().strip().lower()
            device_id = (dev / "device").read_text().strip().lower()
            
            # Read device name if available
            name = ""
            for probe_file in ["label", "product_name"]:
                f = dev / probe_file
                if f.is_file():
                    name = f.read_text().strip()
                    break

            gpus.append({
                "pci_id": dev.name,
                "vendor": vendor,
                "device_id": device_id,
                "name": name,
            })
        except Exception:
            continue

    return gpus


def _detect_via_lspci() -> list[dict[str, str]]:
    """Scan lspci for display devices if lspci is installed."""
    lspci = shutil.which("lspci")
    if not lspci:
        return []

    found = []
    try:
        res = subprocess.run([lspci, "-nn"], capture_output=True, text=True, timeout=3)
        for line in res.stdout.splitlines():
            if any(k in line.lower() for k in ("vga compatible", "3d controller", "display controller")):
                line_lower = line.lower()
                vendor = "unknown"
                if "1002:" in line_lower or "advanced micro devices" in line_lower or "amd" in line_lower:
                    vendor = VENDOR_AMD
                elif "10de:" in line_lower or "nvidia" in line_lower:
                    vendor = VENDOR_NVIDIA
                elif "8086:" in line_lower or "intel" in line_lower:
                    vendor = VENDOR_INTEL
                found.append({"raw": line, "vendor": vendor})
    except Exception:
        pass
    return found


def _find_render_node() -> str | None:
    """Find the default Linux DRI render node (/dev/dri/renderD128, etc.)."""
    dri_dir = Path("/dev/dri")
    if not dri_dir.is_dir():
        return None

    # Render nodes take priority
    render_nodes = sorted(dri_dir.glob("renderD*"))
    if render_nodes:
        return str(render_nodes[0])

    card_nodes = sorted(dri_dir.glob("card*"))
    if card_nodes:
        return str(card_nodes[0])

    return None


def detect_gpu() -> GPUInfo:
    """Detect the host GPU and return recommended encoder settings.

    Prioritizes:
    1. AMD GPU (e.g. RX 7700 XT with AV1 VA-API).
    2. NVIDIA GPU (with NVENC HEVC/AV1 via CUDA).
    3. Intel GPU (with QSV/VA-API).
    4. Software fallback.
    """
    render_node = _find_render_node()
    pci_gpus = _read_sysfs_pci_gpus()
    lspci_gpus = _detect_via_lspci()

    # --- 1. Check for AMD Radeon ---
    is_amd = any(g.get("vendor") == VENDOR_AMD for g in pci_gpus) or any(
        g.get("vendor") == VENDOR_AMD for g in lspci_gpus
    )

    # Check /sys/class/drm/renderD*/device/vendor
    if not is_amd and render_node:
        try:
            node_name = Path(render_node).name
            vendor_path = Path(f"/sys/class/drm/{node_name}/device/vendor")
            if vendor_path.is_file() and vendor_path.read_text().strip().lower() == VENDOR_AMD:
                is_amd = True
        except Exception:
            pass

    if is_amd or (render_node and not shutil.which("nvidia-smi") and not any(g.get("vendor") == VENDOR_NVIDIA for g in pci_gpus)):
        # Look for model identifier
        model_name = "AMD Radeon GPU"
        supports_av1 = False

        for g in pci_gpus:
            if g.get("vendor") == VENDOR_AMD:
                # Check for RDNA 3 / Navi 3x (RX 7000 series: 7600, 7700, 7800, 7900)
                # Navi 32 / 7700 XT / 7800 XT device IDs start with 74
                dev_id = g.get("device_id", "").lower()
                if any(k in dev_id for k in ("0x7470", "0x7471", "0x7479", "0x747e", "0x7480", "0x7440", "0x7448")):
                    model_name = "AMD Radeon RX 7000 Series (RDNA 3 / Navi 3x)"
                    supports_av1 = True

        for g in lspci_gpus:
            raw = g.get("raw", "")
            if "7700" in raw or "7800" in raw or "7900" in raw or "7600" in raw:
                model_name = "AMD Radeon RX 7000 Series (AV1 Hardware Encode)"
                supports_av1 = True
            elif "radeon" in raw.lower() or "amd" in raw.lower():
                model_name = raw.split(":")[-1].strip()

        # If user explicitly has 7700 XT or vainfo verifies AV1 encode:
        if _check_vainfo_av1_encode() or "7700" in model_name or "7800" in model_name or "7900" in model_name or "7600" in model_name or "rdna 3" in model_name.lower():
            supports_av1 = True

        codecs = ["av1", "hevc", "h264"] if supports_av1 else ["hevc", "h264"]
        rec_codec = "av1" if supports_av1 else "hevc"
        rec_enc = "av1_vaapi" if supports_av1 else "hevc_vaapi"

        return GPUInfo(
            vendor="amd",
            name=model_name,
            device_path=render_node or "/dev/dri/renderD128",
            supported_codecs=codecs,
            recommended_codec=rec_codec,
            recommended_encoder=rec_enc,
            backend="vaapi",
            is_hardware=True,
        )

    # --- 2. Check for NVIDIA ---
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            res = subprocess.run(
                [nvidia_smi, "--query-gpu=name,driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().split(",")]
                nv_name = parts[0]
                driver_ver = parts[1] if len(parts) > 1 else None

                # Ada Lovelace (RTX 40xx) or Blackwell (RTX 50xx) have AV1 NVENC
                supports_av1 = any(k in nv_name for k in ("RTX 40", "RTX 50", "Ada", "Blackwell", "A16", "L4"))
                codecs = ["av1", "hevc", "h264"] if supports_av1 else ["hevc", "h264"]
                rec_codec = "av1" if supports_av1 else "hevc"
                rec_enc = "av1_nvenc" if supports_av1 else "hevc_nvenc"

                return GPUInfo(
                    vendor="nvidia",
                    name=nv_name,
                    device_path=None,  # Handled via NVIDIA Container Toolkit / --gpus all
                    supported_codecs=codecs,
                    recommended_codec=rec_codec,
                    recommended_encoder=rec_enc,
                    backend="nvenc",
                    is_hardware=True,
                    driver_version=driver_ver,
                )
        except Exception:
            pass

    # --- 3. Check for Intel (Arc / Iris / UHD) ---
    is_intel = any(g.get("vendor") == VENDOR_INTEL for g in pci_gpus) or any(
        g.get("vendor") == VENDOR_INTEL for g in lspci_gpus
    )
    if is_intel and render_node:
        supports_av1 = _check_vainfo_av1_encode()
        codecs = ["av1", "hevc", "h264"] if supports_av1 else ["hevc", "h264"]
        rec_codec = "av1" if supports_av1 else "hevc"
        rec_enc = "av1_vaapi" if supports_av1 else "hevc_vaapi"

        return GPUInfo(
            vendor="intel",
            name="Intel Graphics (VA-API / QSV)",
            device_path=render_node,
            supported_codecs=codecs,
            recommended_codec=rec_codec,
            recommended_encoder=rec_enc,
            backend="vaapi",
            is_hardware=True,
        )

    # --- 4. Fallback: CPU Software Encoding ---
    return GPUInfo(
        vendor="software",
        name="CPU Software Encoder",
        device_path=None,
        supported_codecs=["av1", "hevc", "h264"],
        recommended_codec="hevc",
        recommended_encoder="libx265",
        backend="software",
        is_hardware=False,
    )
