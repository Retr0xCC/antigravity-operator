"""CLI entrypoint and subcommand dispatch for Antigravity Operator."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from core.gpu import detect_gpu
from core.launcher import run_sandbox_planner, resolve_kit_path
from core.plan import execute_plan, load_plan, validate_plan, PlanError


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check host readiness for running Antigravity Operator."""
    print("==> Checking Host Environment for Antigravity Operator...")
    all_ok = True

    # 1. Sandbox Engine
    sbx_bin = shutil.which("sbx")
    docker_bin = shutil.which("docker")
    if sbx_bin:
        print(f"  [✓] Docker Sandboxes (sbx): {sbx_bin}")
    elif docker_bin:
        print(f"  [!] Docker Sandboxes (sbx): not found (fallback to docker: {docker_bin})")
    else:
        print("  [✗] Sandbox Engine: neither 'sbx' nor 'docker' found in PATH.")
        all_ok = False

    # 2. Host Media Tools
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    mkvmerge = shutil.which("mkvmerge")
    if ffmpeg and ffprobe:
        print(f"  [✓] Host FFmpeg & FFprobe:  {ffmpeg}")
    else:
        print("  [!] Host FFmpeg: not found on host (needed for host transcode execution).")

    if mkvmerge:
        print(f"  [✓] Host MKVToolNix:        {mkvmerge}")
    else:
        print("  [-] Host MKVToolNix:        not installed (ffmpeg used as remux fallback).")

    # 3. Hardware Acceleration
    gpu = detect_gpu()
    if gpu.is_hardware:
        av1_badge = " [AV1 Encode Supported]" if gpu.supports_av1 else ""
        print(f"  [✓] Hardware GPU:           {gpu.name} ({gpu.backend.upper()}){av1_badge}")
        if gpu.device_path:
            print(f"      DRI Device:             {gpu.device_path}")
        print(f"      Codecs:                 {', '.join(c.upper() for c in gpu.supported_codecs)}")
        print(f"      Default Encoder:        {gpu.recommended_encoder}")
    else:
        print(f"  [-] Hardware GPU:           None detected (fallback to CPU: {gpu.recommended_encoder})")

    # 4. Kit Location
    kit_path = resolve_kit_path()
    print(f"  [✓] Media Operator Kit:     {kit_path}")

    if all_ok:
        print("\nAll core host requirements are satisfied!")
        return 0
    else:
        print("\nSome components are missing. Review messages above.", file=sys.stderr)
        return 1


def cmd_plan(args: argparse.Namespace) -> int:
    """Run read-only sandbox planning to produce plan.json and summary.md."""
    src = Path(args.source).resolve()
    dst = Path(args.dest or src.parent).resolve()
    out = Path(args.out or (Path.cwd() / "out")).resolve()

    ret, plan_file = run_sandbox_planner(
        source_dir=src,
        dest_dir=dst,
        out_dir=out,
        mode=args.mode,
        quality=args.quality,
        max_bitrate=args.max_bitrate,
        force_reencode=args.force_reencode,
        headless=getattr(args, "headless", False),
        custom_image=getattr(args, "image", None),
    )

    if plan_file and plan_file.is_file():
        print(f"[✓] Plan generated successfully: {plan_file}")
        print(f"    To execute this plan on host, run: bin/operate apply {plan_file}")
        return 0
    elif ret != 0:
        return ret
    else:
        print("[-] Sandbox finished, but no plan.json was generated.", file=sys.stderr)
        return 1


def cmd_apply(args: argparse.Namespace) -> int:
    """Safely apply a generated plan.json on the host filesystem."""
    plan_file = Path(args.plan_file).resolve()
    if not plan_file.is_file():
        print(f"[-] Plan file not found: {plan_file}", file=sys.stderr)
        return 1

    try:
        ok = execute_plan(plan_file, dry_run=args.dry_run)
        if ok:
            print("\n[✓] Plan execution completed successfully!")
            return 0
        else:
            print("\n[-] Plan execution finished with errors.", file=sys.stderr)
            return 1
    except PlanError as e:
        print(f"[-] Plan error: {e}", file=sys.stderr)
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Full workflow: generate plan in read-only sandbox, then prompt to apply on host."""
    src = Path(args.source).resolve()
    dst = Path(args.dest or src.parent).resolve()
    out = Path(args.out or (Path.cwd() / "out")).resolve()

    ret, plan_file = run_sandbox_planner(
        source_dir=src,
        dest_dir=dst,
        out_dir=out,
        mode=args.mode,
        quality=args.quality,
        max_bitrate=args.max_bitrate,
        force_reencode=args.force_reencode,
        headless=getattr(args, "headless", False),
        custom_image=getattr(args, "image", None),
    )

    if ret != 0 or not plan_file or not plan_file.is_file():
        print("[-] Planning failed or produced no plan.json.", file=sys.stderr)
        return ret or 1

    # Ask for confirmation unless --yes is specified
    if getattr(args, "yes", False):
        user_apply = True
    else:
        try:
            choice = input("Do you want to apply this plan on the host now? [y/N]: ").strip().lower()
            user_apply = choice in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 1

    if not user_apply:
        print(f"Skipped execution. You can apply it later with: bin/operate apply {plan_file}")
        return 0

    return cmd_apply(argparse.Namespace(plan_file=str(plan_file), dry_run=args.dry_run))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bin/operate",
        description="Antigravity Media Operator: Read-Only Sandbox Planner & Host Executor",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Subcommand: doctor
    subparsers.add_parser("doctor", help="Check host readiness (GPU, SBX/Docker, media tools)")

    # Common arguments helper
    def add_planning_args(p: argparse.ArgumentParser):
        p.add_argument("source", help="Path to input media directory (mounted read-only)")
        p.add_argument("--dest", "-d", help="Target library destination directory on host")
        p.add_argument("--out", "-o", default="./out", help="Output directory for generated plan (default: ./out)")
        p.add_argument("--mode", "-m", choices=["link", "remux", "compress", "full"], default="link", help="Operating mode (default: link)")
        p.add_argument("--quality", "-q", type=int, default=28, help="Transcode target quality (QP/CRF, default: 28)")
        p.add_argument("--max-bitrate", type=int, help="Maximum video bitrate threshold in kbps")
        p.add_argument("--force-reencode", action="store_true", help="Force re-encoding even if codec matches")
        p.add_argument("--image", help="Docker image for sandbox planner (default: auto-detected)")
        p.add_argument("--headless", action="store_true", help="Run planning non-interactively and exit automatically")
        p.add_argument("--dry-run", action="store_true", help="Simulate execution without modifying files")

    # Subcommand: plan
    p_plan = subparsers.add_parser("plan", help="Generate plan.json inside read-only sandbox without applying")
    add_planning_args(p_plan)

    # Subcommand: apply
    p_apply = subparsers.add_parser("apply", help="Execute an existing plan.json on the host")
    p_apply.add_argument("plan_file", help="Path to plan.json")
    p_apply.add_argument("--dry-run", action="store_true", help="Simulate execution without modifying files")

    # Subcommand: run
    p_run = subparsers.add_parser("run", help="Generate plan in sandbox, review summary, and apply on host")
    add_planning_args(p_run)
    p_run.add_argument("-y", "--yes", action="store_true", help="Automatically apply plan without interactive confirmation")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "doctor":
        return cmd_doctor(args)
    elif args.subcommand == "plan":
        return cmd_plan(args)
    elif args.subcommand == "apply":
        return cmd_apply(args)
    elif args.subcommand == "run":
        return cmd_run(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
