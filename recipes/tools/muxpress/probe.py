"""Media probing utilities using ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def check_ffmpeg_tools() -> tuple[bool, str | None]:
    """Check if ffmpeg and ffprobe are installed and available in PATH."""
    missing = []
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg")
    if not shutil.which("ffprobe"):
        missing.append("ffprobe")

    if missing:
        return False, f"Required tool(s) not found in system PATH: {', '.join(missing)}"
    return True, None


def probe_file(filepath: Path) -> dict:
    """Run ffprobe on a file and return parsed JSON metadata.

    Returns empty dict if ffprobe fails or file cannot be probed.
    """
    if not filepath.is_file():
        return {}

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(filepath),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            return {}
        return json.loads(res.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return {}


def get_video_codec(filepath: Path, probe_data: dict | None = None) -> str | None:
    """Get the codec_name of the first video stream in the file (e.g. 'av1', 'hevc', 'h264')."""
    data = probe_data if probe_data is not None else probe_file(filepath)
    streams = data.get("streams", [])

    for stream in streams:
        if stream.get("codec_type") == "video":
            return stream.get("codec_name", "").lower() or None

    return None


def is_hevc(filepath: Path, probe_data: dict | None = None) -> bool:
    """Check if the first video stream in the file is already encoded in HEVC (H.265)."""
    codec = get_video_codec(filepath, probe_data)
    return codec in {"hevc", "h265"}


def is_av1(filepath: Path, probe_data: dict | None = None) -> bool:
    """Check if the first video stream in the file is already encoded in AV1."""
    codec = get_video_codec(filepath, probe_data)
    return codec == "av1"


def is_already_encoded(filepath: Path, target_codec: str = "hevc", probe_data: dict | None = None) -> bool:
    """Check if file is already encoded in target_codec or a more advanced codec."""
    codec = get_video_codec(filepath, probe_data)
    if not codec:
        return False
    if target_codec == "av1":
        return codec == "av1"
    if target_codec in {"hevc", "h265"}:
        return codec in {"hevc", "h265", "av1"}
    return codec == target_codec


def get_first_audio_title(filepath: Path, probe_data: dict | None = None) -> str | None:
    """Get the title or language of the first audio stream in the file if present."""
    data = probe_data if probe_data is not None else probe_file(filepath)
    streams = data.get("streams", [])

    for stream in streams:
        if stream.get("codec_type") == "audio":
            tags = stream.get("tags", {})
            return tags.get("title") or tags.get("language")

    return None
