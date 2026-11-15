"""Command-line interface for Muxpress."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .models import EncoderSettings, PipelineConfig
from .pipeline import run_pipeline
from .tui import run_interactive_wizard


def build_parser() -> argparse.ArgumentParser:
    """Create and configure the ArgumentParser."""
    parser = argparse.ArgumentParser(
        prog="muxpress",
        description="Muxpress: Fast anime/series muxing and NVENC HEVC compression tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  muxpress                                   # Start interactive setup wizard (when run in terminal)
  muxpress /path/to/series                   # Full cycle for series folder: merge and compress
  muxpress movie.mkv                         # Full cycle for single movie/OVA file
  muxpress movie.mkv --merge-only            # Only merge external tracks/fonts for movie
  muxpress movie.mkv --compress-only         # Only run NVENC compression on movie
  muxpress /path/to/series --merge-only      # Merge only (fast remux without re-encoding)
  muxpress /path/to/series --compress-only   # Compress existing MKV files only
  muxpress movie.mkv --dry-run               # Inspect what would be merged/compressed
  muxpress . -t "Frieren" -s 1 --offset 0    # Set custom title and season
  muxpress -i                                # Force launch interactive TUI wizard
        """,
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to folder containing series episodes OR path to a single .mkv file (default: current directory).",
    )

    parser.add_argument(
        "-t", "--title",
        dest="title",
        default=None,
        help="Custom series or movie title override (default: auto-detected from filenames).",
    )

    parser.add_argument(
        "-s", "--season",
        dest="season",
        type=int,
        default=None,
        help="Custom season number override (default: auto-detected).",
    )

    parser.add_argument(
        "--offset",
        dest="offset",
        type=int,
        default=0,
        help="Episode number offset to subtract (e.g. 88 to convert ep 89 into 1, default: 0).",
    )

    parser.add_argument(
        "-o", "--output-dir",
        dest="output_dir",
        default="merge-output",
        help="Output directory name or path for merged files (default: 'merge-output').",
    )

    # Mutually exclusive operation modes
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--merge-only",
        "--no-compress",
        dest="merge_only",
        action="store_true",
        help="Only merge audio, subs, and fonts into MKV without NVENC compression.",
    )
    mode_group.add_argument(
        "--compress-only",
        action="store_true",
        help="Only run NVENC compression on existing MKV files without merging.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what files would be processed and print FFmpeg commands without executing them.",
    )

    # Hardware Encoder options (VA-API / NVENC / CPU)
    encoder_group = parser.add_argument_group("Hardware & Software Encoder Options")
    encoder_group.add_argument(
        "--backend",
        choices=["vaapi", "nvenc", "software"],
        default=os.environ.get("OPERATE_GPU_BACKEND", "vaapi"),
        help="Encoding backend: 'vaapi' (AMD / Intel), 'nvenc' (NVIDIA), 'software' (CPU). Default: env OPERATE_GPU_BACKEND or vaapi.",
    )
    encoder_group.add_argument(
        "--codec",
        choices=["av1", "hevc", "h264"],
        default=os.environ.get("OPERATE_VIDEO_CODEC", "av1"),
        help="Target video compression codec: 'av1', 'hevc', 'h264' (default: env OPERATE_VIDEO_CODEC or av1).",
    )
    encoder_group.add_argument(
        "--preset",
        default="p6",
        help="Encoding preset (e.g. p1-p7 for NVENC, 1-8 for SVT-AV1, default: p6).",
    )
    encoder_group.add_argument(
        "-q", "--quality", "--qp",
        dest="quality",
        type=int,
        default=int(os.environ.get("OPERATE_NVENC_QP", "28")),
        help="Constant quality parameter (global_quality for VA-API, QP for NVENC, CRF for CPU. Default: 28).",
    )
    encoder_group.add_argument(
        "--device",
        default=os.environ.get("OPERATE_DRI_DEVICE", None),
        help="DRI render device path for VA-API (e.g. /dev/dri/renderD128).",
    )
    encoder_group.add_argument(
        "--gpu",
        type=int,
        default=0,
        help="GPU device index for NVENC (default: 0).",
    )
    encoder_group.add_argument(
        "--force-reencode",
        "--force-hevc",
        dest="force_reencode",
        action="store_true",
        default=(os.environ.get("OPERATE_FORCE_HEVC") == "1"),
        help="Re-encode video stream even if it is already encoded in the target codec.",
    )

    # Safety and Source management
    parser.add_argument(
        "--delete-sources",
        action="store_true",
        default=False,
        help="Delete source video, audio, and subtitle files after successful merge (default: False).",
    )

    # Interactive and verbosity
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Launch interactive setup wizard with arrow-key menu and Tab auto-complete.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show full FFmpeg commands and detailed stream info.",
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Check if interactive wizard should be launched:
    # 1. Explicitly requested with -i / --interactive
    # 2. Or executed in an interactive terminal with no arguments at all
    args_list = sys.argv[1:] if argv is None else argv
    is_interactive_terminal = sys.stdin.isatty() and sys.stdout.isatty()
    should_launch_wizard = args.interactive or (
        len(args_list) == 0 and is_interactive_terminal
    )

    if should_launch_wizard and is_interactive_terminal:
        config = run_interactive_wizard()
        if config is None:
            return 0
        return run_pipeline(config)

    target_path = Path(args.path)

    encoder_settings = EncoderSettings(
        backend=args.backend,
        codec=args.codec,
        preset=args.preset,
        quality=args.quality,
        device=args.device,
        gpu=args.gpu,
        force_reencode=args.force_reencode,
    )

    config = PipelineConfig(
        target_path=target_path,
        output_dir=Path(args.output_dir),
        custom_title=args.title,
        custom_season=args.season,
        episode_offset=args.offset,
        merge_only=args.merge_only,
        compress_only=args.compress_only,
        dry_run=args.dry_run,
        delete_sources=args.delete_sources,
        interactive=args.interactive,
        verbose=args.verbose,
        encoder=encoder_settings,
    )

    return run_pipeline(config)


if __name__ == "__main__":
    sys.exit(main())
