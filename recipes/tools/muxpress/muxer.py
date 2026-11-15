"""FFmpeg muxing command builder and executor."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .models import EpisodePlan, TrackType


def build_mux_command(plan: EpisodePlan, has_original_audio: bool = True) -> list[str]:
    """Build the exact FFmpeg command arguments for remuxing an episode.

    Preserves original video and audio, maps all external audio/subtitles with metadata,
    and attaches fonts with proper MIME types using stream-copy (-c copy).
    """
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(plan.source_video),
    ]

    input_counter = 1

    # Add external audio files as inputs
    for track in plan.audio_tracks:
        cmd.extend(["-i", str(track.path)])
        input_counter += 1

    # Add external subtitle files as inputs
    for track in plan.subtitle_tracks:
        cmd.extend(["-i", str(track.path)])
        input_counter += 1

    # Add fonts as attachments
    for font in plan.fonts:
        cmd.extend(["-attach", str(font.path)])

    # Map video stream 0:v:0
    cmd.extend(["-map", "0:v:0"])

    # Track counters for metadata indexing
    audio_track_counter = 0

    # Map source audio if present
    if has_original_audio:
        cmd.extend(["-map", "0:a:0?"])
        cmd.extend([f"-metadata:s:a:{audio_track_counter}", 'title=Japanese (Original)'])
        audio_track_counter += 1

    # Map external audio tracks
    curr_input = 1
    for track in plan.audio_tracks:
        cmd.extend(["-map", f"{curr_input}:a:{track.stream_index}"])
        cmd.extend([
            f"-metadata:s:a:{audio_track_counter}", f"language={track.language}",
            f"-metadata:s:a:{audio_track_counter}", f"title={track.title}",
        ])
        curr_input += 1
        audio_track_counter += 1

    # Map external subtitle tracks
    sub_track_counter = 0
    for track in plan.subtitle_tracks:
        cmd.extend(["-map", f"{curr_input}:s:{track.stream_index}"])
        cmd.extend([
            f"-metadata:s:s:{sub_track_counter}", f"language={track.language}",
            f"-metadata:s:s:{sub_track_counter}", f"title={track.title}",
        ])
        curr_input += 1
        sub_track_counter += 1

    # Attach fonts metadata
    for attachment_counter, font in enumerate(plan.fonts):
        cmd.extend([f"-metadata:s:t:{attachment_counter}", f"mimetype={font.mime_type}"])

    # Lossless stream copy
    cmd.extend(["-c", "copy"])

    # Output file
    cmd.append(str(plan.output_path))

    return cmd


def format_mux_command_for_dry_run(cmd: list[str], font_count: int = 0) -> str:
    """Format FFmpeg mux command for dry-run display, collapsing font attachments."""
    filtered_args: list[str] = []
    i = 0
    font_stub_added = False
    stub_token = f"[+ {font_count} fonts attached]" if font_count > 0 else ""

    while i < len(cmd):
        arg = cmd[i]
        if arg == "-attach":
            # Skip -attach and the font file path
            i += 2
            continue
        elif arg.startswith("-metadata:s:t:"):
            # Skip -metadata:s:t:N and the mimetype=... argument
            i += 2
            continue
        elif arg == "-c" and font_count > 0 and not font_stub_added:
            # Insert the font placeholder before -c copy
            filtered_args.append(stub_token)
            font_stub_added = True
            filtered_args.append(arg)
            i += 1
        else:
            filtered_args.append(arg)
            i += 1

    if font_count > 0 and not font_stub_added:
        filtered_args.append(stub_token)

    parts: list[str] = []
    for arg in filtered_args:
        if arg == stub_token:
            parts.append(arg)
        elif " " in arg:
            parts.append(f'"{arg}"')
        else:
            parts.append(arg)

    return " ".join(parts)


def execute_mux(
    plan: EpisodePlan,
    dry_run: bool = False,
    verbose: bool = False,
    has_original_audio: bool = True,
) -> bool:
    """Execute FFmpeg muxing process for an episode.

    Returns True on success, False on failure.
    """
    cmd = build_mux_command(plan, has_original_audio=has_original_audio)

    if dry_run:
        if verbose:
            print(f"[DRY-RUN] Mux command for {plan.formatted_code}:")
            display_cmd = format_mux_command_for_dry_run(cmd, font_count=len(plan.fonts))
            print("  " + display_cmd)
        return True

    # Ensure parent output directory exists
    plan.output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if verbose:
            print(">>> Running FFmpeg:")
            print("  " + " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd))

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if not verbose else None,
            stderr=subprocess.PIPE if not verbose else None,
            check=False,
            text=True,
        )

        if res.returncode == 0 and plan.output_path.is_file() and plan.output_path.stat().st_size > 0:
            return True

        if verbose and res.stderr:
            print(f"FFmpeg error: {res.stderr}", file=sys.stderr)

        # Cleanup failed output file if created
        if plan.output_path.is_file():
            plan.output_path.unlink(missing_ok=True)
        return False

    except (subprocess.SubprocessError, OSError) as e:
        if verbose:
            print(f"Exception during muxing: {e}", file=sys.stderr)
        if plan.output_path.is_file():
            plan.output_path.unlink(missing_ok=True)
        return False
