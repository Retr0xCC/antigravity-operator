"""Pipeline orchestrator for discovery, muxing, compression, and cleanup."""

from __future__ import annotations

import sys
from pathlib import Path

from .cleanup import safe_cleanup_sources
from .encoder import compress_video
from .models import PipelineConfig
from .muxer import execute_mux
from .probe import check_ffmpeg_tools, is_already_encoded, is_hevc, probe_file
from .scanner import (
    build_episode_plan,
    discover_fonts,
    discover_track_directories,
)


def run_pipeline(config: PipelineConfig) -> int:
    """Execute the configured pipeline for either a directory or a single file."""
    # Verify ffmpeg/ffprobe unless dry_run
    if not config.dry_run:
        ok, err = check_ffmpeg_tools()
        if not ok:
            print(f"Error: {err}", file=sys.stderr)
            return 1

    target = config.target_path.resolve()

    if not target.exists():
        print(f"Error: Path '{target}' does not exist.", file=sys.stderr)
        return 1

    if target.is_file():
        if target.suffix.lower() != ".mkv":
            print(f"Error: File '{target.name}' is not an MKV video file (.mkv).", file=sys.stderr)
            return 1
        return run_single_file_pipeline(config, target)

    if target.is_dir():
        if config.compress_only:
            return run_compress_only(config, target)
        return run_batch_merge_pipeline(config, target)

    print(f"Error: Unsupported path type '{target}'.", file=sys.stderr)
    return 1


def run_single_file_pipeline(config: PipelineConfig, video_file: Path) -> int:
    """Run pipeline for a single MKV file (e.g. anime movie or OVA)."""
    parent_dir = video_file.parent
    output_dir = (parent_dir / config.output_dir) if not config.output_dir.is_absolute() else config.output_dir

    print(f">>> Target file:   {video_file.name}")
    print(f">>> Search folder: {parent_dir}")

    # Mode 1: Compress-only
    if config.compress_only:
        print(f">>> Mode: Compress-only (Preset={config.encoder.preset}, QP={config.encoder.qp}, GPU={config.encoder.gpu})")
        print("-" * 60)
        success, msg = compress_video(video_file, config.encoder, dry_run=config.dry_run, verbose=config.verbose)
        print(f"  --> {msg}")
        return 0 if success else 1

    # Mode 2: Merge or Full cycle
    sound_dirs, subs_dirs = discover_track_directories(parent_dir)
    fonts = discover_fonts(parent_dir, exclude_dir=output_dir)

    plan = build_episode_plan(
        video_file=video_file,
        target_dir=parent_dir,
        output_dir=output_dir,
        sound_dirs=sound_dirs,
        subs_dirs=subs_dirs,
        fonts=fonts,
        custom_title=config.custom_title,
        custom_season=config.custom_season,
        episode_offset=config.episode_offset,
        allow_fallback=True,
    )

    if not plan:
        print(f"Error: Unable to prepare execution plan for '{video_file.name}'", file=sys.stderr)
        return 1

    has_external_assets = bool(plan.audio_tracks or plan.subtitle_tracks or plan.fonts)

    # Check source video codec prior to mux/compression
    probe_info = probe_file(video_file)
    has_audio = True
    if probe_info:
        has_audio = any(s.get("codec_type") == "audio" for s in probe_info.get("streams", []))
    source_already_encoded = is_already_encoded(video_file, target_codec=config.encoder.codec, probe_data=probe_info)

    if has_external_assets:
        print(f">>> External tracks/fonts found for: {plan.title} ({plan.formatted_code})")
        for track in plan.audio_tracks:
            print(f"    + [Audio] {track.title}")
        for track in plan.subtitle_tracks:
            print(f"    + [Subs]  {track.title}")
        if plan.fonts:
            print(f"    + [Fonts] Attaching {len(plan.fonts)} font(s)")
        print("-" * 60)

        if plan.output_path.is_file() and not config.dry_run:
            print(f"⏭️  SKIP: Output file already exists: '{plan.output_path.name}'")
            target_to_compress = plan.output_path
        else:
            mux_ok = execute_mux(
                plan,
                dry_run=config.dry_run,
                verbose=config.verbose,
                has_original_audio=has_audio,
            )

            if not mux_ok:
                print(f"❌ [FAIL] Mux failed for {video_file.name}")
                return 1

            print(f"✅ [OK] Mux completed -> {plan.output_path.name}")

            if config.delete_sources and not config.dry_run:
                print("    🗑️  Removing source files...")
                safe_cleanup_sources(plan.files_to_delete, verbose=config.verbose)

            target_to_compress = plan.output_path

        # Hardware Compression
        if not config.merge_only:
            backend_tag = config.encoder.backend.upper()
            codec_tag = config.encoder.codec.upper()
            if source_already_encoded and not config.encoder.force_reencode:
                print(f"⚡ [{backend_tag}] Skipping compression for {target_to_compress.name}: Source is already encoded in {codec_tag}")
                return 0

            print(f"⚡ [{backend_tag}] Starting {codec_tag} compression for {target_to_compress.name}...")
            comp_ok, comp_msg = compress_video(
                target_to_compress,
                config.encoder,
                dry_run=config.dry_run,
                verbose=config.verbose,
            )
            print(f"    --> {comp_msg}")
            return 0 if comp_ok else 1

        return 0

    else:
        # No external tracks or fonts found
        print(f"ℹ️  [INFO] No external audio, subtitles, or fonts found for '{video_file.name}'.")

        if config.merge_only:
            print("Nothing to merge. Merge stage finished.")
            return 0

        # Full cycle: proceed directly to compression unless already in target codec
        backend_tag = config.encoder.backend.upper()
        codec_tag = config.encoder.codec.upper()
        if source_already_encoded and not config.encoder.force_reencode:
            print(f"⚡ [{backend_tag}] Skipping compression for {video_file.name}: Source is already encoded in {codec_tag}")
            return 0

        print(f"⚡ [{backend_tag}] Proceeding directly to {codec_tag} compression for {video_file.name}...")
        comp_ok, comp_msg = compress_video(
            video_file,
            config.encoder,
            dry_run=config.dry_run,
            verbose=config.verbose,
        )
        print(f"    --> {comp_msg}")
        return 0 if comp_ok else 1


def run_compress_only(config: PipelineConfig, target_dir: Path) -> int:
    """Run compression only on existing MKV files."""
    backend_tag = config.encoder.backend.upper()
    codec_tag = config.encoder.codec.upper()
    print(f">>> Scanning MKV files for {backend_tag} {codec_tag} compression in: {target_dir}")
    print(f">>> Settings: Backend={backend_tag}, Codec={codec_tag}, Quality={config.encoder.quality}, Preset={config.encoder.preset}")
    print("-" * 60)

    mkv_files = [
        f for f in sorted(target_dir.rglob("*.mkv"))
        if not f.name.endswith(".temp.mkv")
    ]

    if not mkv_files:
        print("No .mkv files found to compress.")
        return 0

    success_count = 0
    skipped_count = 0
    fail_count = 0

    for file_path in mkv_files:
        print(f"File: {file_path.name}")
        success, msg = compress_video(
            file_path,
            config.encoder,
            dry_run=config.dry_run,
            verbose=config.verbose,
        )
        print(f"  --> {msg}")
        print("-" * 60)

        if "SKIPPED" in msg:
            skipped_count += 1
        elif success:
            success_count += 1
        else:
            fail_count += 1

    print(f"Done! Processed: {len(mkv_files)} | Succeeded: {success_count} | Skipped: {skipped_count} | Failed: {fail_count}")
    return 1 if fail_count > 0 else 0


def run_batch_merge_pipeline(config: PipelineConfig, target_dir: Path) -> int:
    """Run the merge (and optional compression) batch pipeline on a directory."""
    output_dir = (target_dir / config.output_dir) if not config.output_dir.is_absolute() else config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f">>> Target folder: {target_dir}")
    print(f">>> Output folder: {output_dir}")

    sound_dirs, subs_dirs = discover_track_directories(target_dir)

    for s_dir, lang in sound_dirs:
        print(f"🔊 Found sound folder: '{s_dir.name}' [{lang}]")
    for sub_dir, lang in subs_dirs:
        print(f"📝 Found subs folder:  '{sub_dir.name}' [{lang}]")

    fonts = discover_fonts(target_dir, exclude_dir=output_dir)
    if fonts:
        print(f"🔤 Found {len(fonts)} unique font file(s) for attachment")

    print("-" * 60)

    video_files = [
        f for f in sorted(target_dir.iterdir())
        if f.is_file() and f.suffix.lower() == ".mkv" and not f.name.endswith(".temp.mkv")
    ]

    if not video_files:
        print(f"No source .mkv files found in: {target_dir}")
        return 0

    total_episodes = 0
    succeeded_episodes = 0
    skipped_episodes = 0
    failed_episodes = 0

    for video_file in video_files:
        plan = build_episode_plan(
            video_file=video_file,
            target_dir=target_dir,
            output_dir=output_dir,
            sound_dirs=sound_dirs,
            subs_dirs=subs_dirs,
            fonts=fonts,
            custom_title=config.custom_title,
            custom_season=config.custom_season,
            episode_offset=config.episode_offset,
            allow_fallback=True,
        )

        if not plan:
            print(f"⚠️  SKIP: Cannot parse episode format from filename: '{video_file.name}'")
            skipped_episodes += 1
            continue

        total_episodes += 1

        if plan.output_path.is_file():
            print(f"⏭️  SKIP: Episode already assembled: '{plan.output_path.name}'")
            skipped_episodes += 1
            continue

        print(f">>> Assembling: {plan.title} ({plan.formatted_code})")
        for track in plan.audio_tracks:
            print(f"    + [Audio] {track.title}")
        for track in plan.subtitle_tracks:
            print(f"    + [Subs]  {track.title}")
        if plan.fonts:
            print(f"    + [Fonts] Attaching {len(plan.fonts)} font(s)")

        # Check source video codec prior to mux/compression
        probe_info = probe_file(plan.source_video)
        has_audio = True
        if probe_info:
            has_audio = any(s.get("codec_type") == "audio" for s in probe_info.get("streams", []))
        source_already_encoded = is_already_encoded(plan.source_video, target_codec=config.encoder.codec, probe_data=probe_info)

        mux_ok = execute_mux(
            plan,
            dry_run=config.dry_run,
            verbose=config.verbose,
            has_original_audio=has_audio,
        )

        if not mux_ok:
            print(f"❌ [FAIL] Mux failed for {plan.formatted_code}")
            failed_episodes += 1
            print("-" * 60)
            continue

        print(f"✅ [OK] Mux completed -> {plan.output_path.name}")

        if config.delete_sources and not config.dry_run:
            print("    🗑️  Removing source files for episode...")
            safe_cleanup_sources(plan.files_to_delete, verbose=config.verbose)

        if not config.merge_only:
            backend_tag = config.encoder.backend.upper()
            codec_tag = config.encoder.codec.upper()
            if source_already_encoded and not config.encoder.force_reencode:
                print(f"⚡ [{backend_tag}] Skipping compression for {plan.output_path.name}: Source is already encoded in {codec_tag}")
            else:
                print(f"⚡ [{backend_tag}] Starting {codec_tag} compression for {plan.output_path.name}...")
                comp_ok, comp_msg = compress_video(
                    plan.output_path,
                    config.encoder,
                    dry_run=config.dry_run,
                    verbose=config.verbose,
                )
                print(f"    --> {comp_msg}")

        succeeded_episodes += 1
        print("-" * 60)

    print(f"Pipeline finished! Total: {total_episodes} | Succeeded: {succeeded_episodes} | Skipped: {skipped_episodes} | Failed: {failed_episodes}")
    return 1 if failed_episodes > 0 else 0
