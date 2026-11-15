"""Hardware and GPU autodetection for media transcoding on the host system.

Supports AMD (Radeon RX 7000 / RDNA 3 AV1 & HEVC via VA-API),
NVIDIA (NVENC HEVC & AV1 via CUDA), Intel (QSV/VA-API), and CPU fallback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


VENDOR_AMD = "0x1002"
VENDOR_NVIDIA = "0x10de"
VENDOR_INTEL = "0x8086"


@dataclass
class GPUInfo:
    """Detected host hardware accelerator capabilities."""

    vendor: str  # "amd", "nvidia", "intel", "software"
    name: str  # e.g. "AMD Radeon RX 7700 XT"
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

    def to_dict(self) -> dict:
        """Return dict representation suitable for JSON serialization."""
        d = asdict(self)
        d["supports_av1"] = self.supports_av1
        return d


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


def _check_vainfo_hevc_encode() -> bool:
    """Check if vainfo reports VAEntrypointEncSlice for HEVC / H.265."""
    vainfo = shutil.which("vainfo")
    if not vainfo:
        return False
    try:
        res = subprocess.run([vainfo], capture_output=True, text=True, timeout=3)
        out = res.stdout + res.stderr
        for line in out.splitlines():
            if ("VAProfileHEVC" in line or "VAProfileH265" in line) and "VAEntrypointEncSlice" in line:
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
            if not pci_class.startswith("0x03"):
                continue

            vendor = (dev / "vendor").read_text().strip().lower()
            device_id = (dev / "device").read_text().strip().lower()

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

    devices: list[dict[str, str]] = []
    try:
        res = subprocess.run([lspci, "-nn"], capture_output=True, text=True, timeout=3)
        for line in res.stdout.splitlines():
            if any(term in line.lower() for term in ["vga compatible controller", "3d controller", "display controller"]):
                vendor = "unknown"
                if "1002:" in line:
                    vendor = VENDOR_AMD
                elif "10de:" in line:
                    vendor = VENDOR_NVIDIA
                elif "8086:" in line:
                    vendor = VENDOR_INTEL
                devices.append({
                    "raw": line,
                    "vendor": vendor,
                    "name": line.split(": ", 1)[-1] if ": " in line else line,
                })
    except Exception:
        pass
    return devices


def _find_dri_render_node() -> str | None:
    """Find the default DRI render node (e.g. /dev/dri/renderD128)."""
    dri_dir = Path("/dev/dri")
    if not dri_dir.is_dir():
        return None

    render_nodes = sorted(dri_dir.glob("renderD*"))
    if render_nodes:
        return str(render_nodes[0])
    return None


def detect_gpu() -> GPUInfo:
    """Perform comprehensive detection of host GPU and hardware video encoding capabilities."""
    dev_path = _find_dri_render_node()

    # 1. Check NVIDIA via nvidia-smi
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
                line = res.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                gpu_name = parts[0]
                driver = parts[1] if len(parts) > 1 else None

                # RTX 4000 series (Ada Lovelace) supports AV1 NVENC
                supports_av1 = bool(re.search(r"RTX\s+(?:40\d\d|50\d\d|Ada|L4\b|L40)", gpu_name, re.I))
                supported = ["av1", "hevc", "h264"] if supports_av1 else ["hevc", "h264"]
                rec_codec = "av1" if supports_av1 else "hevc"
                rec_enc = "av1_nvenc" if supports_av1 else "hevc_nvenc"

                return GPUInfo(
                    vendor="nvidia",
                    name=gpu_name,
                    device_path=None,
                    supported_codecs=supported,
                    recommended_codec=rec_codec,
                    recommended_encoder=rec_enc,
                    backend="nvenc",
                    is_hardware=True,
                    driver_version=driver,
                )
        except Exception:
            pass

    # 2. Check AMD / Intel via vainfo and sysfs
    has_vainfo_av1 = _check_vainfo_av1_encode()
    has_vainfo_hevc = _check_vainfo_hevc_encode()

    sysfs_gpus = _read_sysfs_pci_gpus()
    lspci_gpus = _detect_via_lspci()

    # Check AMD
    is_amd = any(g.get("vendor") == VENDOR_AMD for g in sysfs_gpus) or any(g.get("vendor") == VENDOR_AMD for g in lspci_gpus)
    if is_amd:
        # Detect card name
        name = "AMD Radeon Graphics"
        for g in sysfs_gpus + lspci_gpus:
            raw = g.get("name") or g.get("raw") or ""
            if "radeon" in raw.lower() or "amd" in raw.lower():
                name = raw
                break

        # Check for RX 7000 / RDNA 3 (e.g. 7700 XT, 7800 XT, 7900 XT)
        supports_av1 = has_vainfo_av1 or bool(re.search(r"(?:RX\s+7\d\d\d|Navi\s+3|RDNA\s*3)", name, re.I))
        supported = ["av1", "hevc", "h264"] if supports_av1 else ["hevc", "h264"]
        rec_codec = "av1" if supports_av1 else "hevc"
        rec_enc = "av1_vaapi" if supports_av1 else "hevc_vaapi"

        return GPUInfo(
            vendor="amd",
            name=name,
            device_path=dev_path or "/dev/dri/renderD128",
            supported_codecs=supported,
            recommended_codec=rec_codec,
            recommended_encoder=rec_enc,
            backend="vaapi",
            is_hardware=True,
        )

    # Check Intel
    is_intel = any(g.get("vendor") == VENDOR_INTEL for g in sysfs_gpus) or any(g.get("vendor") == VENDOR_INTEL for g in lspci_gpus)
    if is_intel:
        name = "Intel Graphics"
        for g in sysfs_gpus + lspci_gpus:
            raw = g.get("name") or g.get("raw") or ""
            if "intel" in raw.lower() or "arc" in raw.lower() or "uhd" in raw.lower():
                name = raw
                break

        supports_av1 = has_vainfo_av1 or bool(re.search(r"(?:Arc|Battlemage|Meteor\s*Lake|Lunar\s*Lake)", name, re.I))
        supported = ["av1", "hevc", "h264"] if supports_av1 else ["hevc", "h264"]
        rec_codec = "av1" if supports_av1 else "hevc"
        rec_enc = "av1_vaapi" if supports_av1 else "hevc_vaapi"

        return GPUInfo(
            vendor="intel",
            name=name,
            device_path=dev_path or "/dev/dri/renderD128",
            supported_codecs=supported,
            recommended_codec=rec_codec,
            recommended_encoder=rec_enc,
            backend="vaapi",
            is_hardware=True,
        )

    # 3. Fallback to CPU Software Encoding
    return GPUInfo(
        vendor="software",
        name="CPU Software Encoder",
        device_path=None,
        supported_codecs=["hevc", "h264"],
        recommended_codec="hevc",
        recommended_encoder="libx265",
        backend="software",
        is_hardware=False,
    )
