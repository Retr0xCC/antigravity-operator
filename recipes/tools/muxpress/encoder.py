"""Multi-backend video compression engine supporting AMD VA-API, NVIDIA NVENC, and CPU.

Features:
- AMD Radeon RX 7000 / RDNA 3 AV1 & HEVC hardware compression via VA-API.
- NVIDIA NVENC HEVC & AV1 compression via CUDA.
- CPU fallback (SVT-AV1, x265).
- Atomic commit with TempFileGuard and rollback protection.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .cleanup import TempFileGuard
from .models import EncoderSettings
from .probe import is_already_encoded, get_video_codec


def get_default_render_device() -> str:
    """Find the default DRI render node."""
    env_dev = os.environ.get("OPERATE_DRI_DEVICE")
    if env_dev and os.path.exists(env_dev):
        return env_dev

    dri_dir = Path("/dev/dri")
    if dri_dir.is_dir():
        render_nodes = sorted(dri_dir.glob("renderD*"))
        if render_nodes:
            return str(render_nodes[0])
    return "/dev/dri/renderD128"


def build_vaapi_command(
    input_file: Path,
    temp_output: Path,
    settings: EncoderSettings,
) -> list[str]:
    """Build FFmpeg command for VA-API (AMD Radeon / Intel).

    Optimized for AMD Radeon RX 7000 Series (AV1 & HEVC 10-bit).
    """
    device = settings.device or get_default_render_device()
    codec = settings.codec.lower()

    if codec == "av1":
        enc_name = "av1_vaapi"
    elif codec in ("hevc", "h265"):
        enc_name = "hevc_vaapi"
    else:
        enc_name = "h264_vaapi"

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel", "warning",
        "-stats",
        "-vaapi_device", device,
        "-i", str(input_file),
        "-map", "0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", "copy",
        "-c:d", "copy",
        "-c:t", "copy",
        "-c:v:0", enc_name,
        "-vf", "format=nv12|p010,hwupload",
        "-rc_mode", "CQP",
        "-global_quality", str(settings.quality),
    ]

    cmd.append(str(temp_output))
    return cmd


def build_nvenc_command(
    input_file: Path,
    temp_output: Path,
    settings: EncoderSettings,
) -> list[str]:
    """Build FFmpeg command for NVIDIA NVENC HEVC/AV1 10-bit compression."""
    codec = settings.codec.lower()
    enc_name = "av1_nvenc" if codec == "av1" else "hevc_nvenc"

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel", "warning",
        "-stats",
        "-hwaccel", "cuda",
        "-i", str(input_file),
        "-map", "0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", "copy",
        "-c:d", "copy",
        "-c:t", "copy",
        "-c:v:0", enc_name,
        "-profile:v", "main10",
        "-pix_fmt", "p010le",
        "-preset", settings.preset,
        "-rc", "constqp",
        "-qp", str(settings.quality),
    ]

    if settings.gpu is not None and str(settings.gpu) != "0":
        cmd.extend(["-gpu", str(settings.gpu)])

    cmd.append(str(temp_output))
    return cmd


def build_software_command(
    input_file: Path,
    temp_output: Path,
    settings: EncoderSettings,
) -> list[str]:
    """Build FFmpeg command for CPU software compression (SVT-AV1 / x265)."""
    codec = settings.codec.lower()

    if codec == "av1":
        enc_name = "libsvtav1"
        quality_args = ["-crf", str(settings.quality), "-preset", "6", "-pix_fmt", "yuv420p10le"]
    elif codec in ("hevc", "h265"):
        enc_name = "libx265"
        quality_args = ["-crf", str(settings.quality), "-preset", "medium", "-pix_fmt", "yuv420p10le"]
    else:
        enc_name = "libx264"
        quality_args = ["-crf", str(settings.quality), "-preset", "medium"]

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel", "warning",
        "-stats",
        "-i", str(input_file),
        "-map", "0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", "copy",
        "-c:d", "copy",
        "-c:t", "copy",
        "-c:v:0", enc_name,
    ] + quality_args + [str(temp_output)]

    return cmd


def build_encode_command(
    input_file: Path,
    temp_output: Path,
    settings: EncoderSettings,
) -> list[str]:
    """Dispatch and construct the appropriate FFmpeg command based on backend."""
    backend = (settings.backend or "vaapi").lower()
    if backend == "nvenc":
        return build_nvenc_command(input_file, temp_output, settings)
    elif backend in ("software", "cpu"):
        return build_software_command(input_file, temp_output, settings)
    else:
        return build_vaapi_command(input_file, temp_output, settings)


def compress_video(
    target_file: Path,
    settings: EncoderSettings,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[bool, str]:
    """Compress target_file using the configured hardware or software encoder.

    Returns:
        (success, message)
    """
    if target_file.is_file():
        # Check if file is already encoded in target codec (or better)
        if not settings.force_reencode and is_already_encoded(target_file, target_codec=settings.codec):
            current_codec = get_video_codec(target_file) or "target codec"
            return True, f"SKIPPED: Already encoded in {current_codec.upper()}"
    elif not dry_run:
        return False, f"File not found: {target_file}"

    temp_output = target_file.with_name(f"{target_file.stem}.temp.mkv")

    cmd = build_encode_command(target_file, temp_output, settings)

    if dry_run:
        if verbose:
            print(f"[DRY-RUN] Compress command ({settings.backend.upper()} - {settings.codec.upper()}) for {target_file.name}:")
            print("  " + " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd))
        return True, "DRY-RUN: Command simulated"

    with TempFileGuard(temp_output) as guard:
        try:
            if verbose:
                print(f">>> Running {settings.backend.upper()} {settings.codec.upper()} compression:")
                print("  " + " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd))

            orig_size = target_file.stat().st_size

            res = subprocess.run(
                cmd,
                stdout=None if verbose else subprocess.DEVNULL,
                stderr=None,  # let FFmpeg print -stats to stderr
                check=False,
            )

            if res.returncode != 0 or not temp_output.is_file() or temp_output.stat().st_size == 0:
                return False, f"ERROR: {settings.backend.upper()} encoding failed with exit code {res.returncode}"

            new_size = temp_output.stat().st_size
            saved_bytes = orig_size - new_size

            if saved_bytes > 0:
                saved_mb = saved_bytes / (1024 * 1024)
                pct = (saved_bytes / orig_size) * 100
                # Atomic file replacement
                os.replace(temp_output, target_file)
                guard.commit()
                return True, f"SUCCESS: Saved {saved_mb:.2f} MB ({pct:.1f}%) via {settings.codec.upper()}"
            else:
                extra_mb = abs(saved_bytes) / (1024 * 1024)
                # Rollback - guard will delete temp_output on exit
                return False, f"ROLLBACK: Compressed file was {extra_mb:.2f} MB larger than original. Kept original."

        except (subprocess.SubprocessError, OSError) as e:
            return False, f"ERROR: Compression aborted due to exception: {e}"
