"""Launcher module for running Antigravity Media Operator inside Docker Sandbox (SBX).

Prepares host hardware profile, provisions output workspace, mounts media strictly
in Read-Only (:ro) mode, and dispatches the planning agent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from core.gpu import detect_gpu


DEFAULT_BASE_KIT = "ghcr.io/retr0xcc/antigravity-kit:latest"
DEFAULT_MIXIN_KIT = "ghcr.io/retr0xcc/media-operator-kit:latest"
DEFAULT_TEMPLATE_IMAGE = "ghcr.io/retr0xcc/antigravity-sbx-patched:latest"


def build_host_profile(
    source_dir: Path,
    dest_dir: Path,
    mode: str = "link",
    quality: int = 28,
    max_bitrate: int | None = None,
    force_reencode: bool = False,
) -> dict:
    """Build host hardware and storage context for the sandbox agent."""
    gpu = detect_gpu()
    return {
        "host_input_path": str(source_dir.resolve()),
        "host_output_path": str(dest_dir.resolve()),
        "mode": mode,
        "quality": quality,
        "max_bitrate": max_bitrate,
        "force_reencode": force_reencode,
        "gpu": gpu.to_dict(),
    }


def write_host_profile(out_dir: Path, profile: dict) -> Path:
    """Save host_profile.json in the output directory."""
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_path = out_dir / "host_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return profile_path


def resolve_base_kit_path() -> str:
    """Find local base antigravity kit or fallback to remote OCI reference."""
    repo_root = Path(__file__).resolve().parent.parent
    neighbor_base = repo_root.parent / "antigravity-sbx-patched" / "kits" / "antigravity"
    if neighbor_base.is_dir() and (neighbor_base / "spec.yaml").is_file():
        return str(neighbor_base.resolve())
    return DEFAULT_BASE_KIT


def resolve_kit_path() -> str:
    """Find local media-operator kit directory or fallback to remote OCI reference."""
    repo_root = Path(__file__).resolve().parent.parent

    # 1. Check neighbor antigravity-sbx-patched
    neighbor_kit = repo_root.parent / "antigravity-sbx-patched" / "kits" / "media-operator"
    if neighbor_kit.is_dir() and (neighbor_kit / "spec.yaml").is_file():
        return str(neighbor_kit.resolve())

    # 2. Check local fallback if present
    local_kit = repo_root / "kits" / "media-operator"
    if local_kit.is_dir() and (local_kit / "spec.yaml").is_file():
        return str(local_kit.resolve())

    return DEFAULT_MIXIN_KIT


def run_sandbox_planner(
    source_dir: Path | str,
    dest_dir: Path | str,
    out_dir: Path | str,
    mode: str = "link",
    quality: int = 28,
    max_bitrate: int | None = None,
    force_reencode: bool = False,
    headless: bool = False,
    base_kit_ref: str | None = None,
    mixin_kit_ref: str | None = None,
    template_image: str | None = None,
) -> tuple[int, Path | None]:
    """Launch the read-only sandbox planner to generate plan.json and summary.md.

    Returns:
        (returncode, plan_json_path or None)
    """
    src = Path(source_dir).resolve()
    dst = Path(dest_dir).resolve()
    out = Path(out_dir).resolve()

    if not src.exists():
        print(f"[-] Source directory does not exist: {src}", file=sys.stderr)
        return 1, None

    out.mkdir(parents=True, exist_ok=True)

    # 1. Prepare host hardware & storage context
    profile = build_host_profile(
        source_dir=src,
        dest_dir=dst,
        mode=mode,
        quality=quality,
        max_bitrate=max_bitrate,
        force_reencode=force_reencode,
    )
    write_host_profile(out, profile)

    # 2. Select runner: sbx (Docker Sandboxes) or standard docker fallback
    sbx_bin = shutil.which("sbx")
    docker_bin = shutil.which("docker")

    effective_base_kit = base_kit_ref or resolve_base_kit_path()
    effective_mixin_kit = mixin_kit_ref or resolve_kit_path()
    effective_template = template_image or DEFAULT_TEMPLATE_IMAGE

    initial_prompt = (
        "Inspect all files in /media/input and generate /media/output/plan.json, "
        "/media/output/summary.md, and /media/output/apply.sh strictly according to "
        "/media/output/host_profile.json and your AGENTS.md instructions."
    )
    prompt_flag = f"-p={initial_prompt}" if headless else f"-i={initial_prompt}"

    print("=" * 72)
    print("  Antigravity Media Operator: Read-Only Planning Sandbox")
    print("=" * 72)
    print(f"  Source (Read-Only): {src}")
    print(f"  Target Destination: {dst}")
    print(f"  Plan Output Dir:    {out}")
    print(f"  Operating Mode:     {mode.upper()}")
    print(f"  Host GPU:           {profile['gpu']['name']} ({profile['gpu']['backend'].upper()})")
    print(f"  Execution Mode:     {'Headless (Auto-exit)' if headless else 'Interactive TUI'}")
    print("=" * 72 + "\n")

    if sbx_bin:
        cmd = [
            sbx_bin, "run", effective_base_kit,
            "--kit", effective_mixin_kit,
            "-v", f"{src}:/media/input:ro",
            "-v", f"{out}:/media/output:rw",
            "--",
            "agy",
            "--dangerously-skip-permissions",
            prompt_flag,
        ]
    elif docker_bin:
        # Fallback to direct Docker container
        cmd = [
            docker_bin, "run", "-it", "--rm",
            "--name", "agy-media-planner",
            "-v", f"{src}:/media/input:ro",
            "-v", f"{out}:/media/output:rw",
            effective_template,
            "agy",
            "--dangerously-skip-permissions",
            prompt_flag,
        ]
    else:
        print("[-] Neither 'sbx' (Docker Sandboxes) nor 'docker' engine found in PATH.", file=sys.stderr)
        return 1, None

    try:
        res = subprocess.run(cmd)
        ret = res.returncode
    except KeyboardInterrupt:
        print("\n[!] Planning aborted by user.")
        return 130, None
    except Exception as e:
        print(f"[-] Failed to launch sandbox: {e}", file=sys.stderr)
        return 1, None

    plan_file = out / "plan.json"
    summary_file = out / "summary.md"

    if summary_file.is_file():
        print("\n" + "=" * 72)
        print("  Generated Plan Summary")
        print("=" * 72)
        try:
            print(summary_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        print("=" * 72 + "\n")

    if plan_file.is_file() and plan_file.stat().st_size > 0:
        return ret, plan_file

    return ret, None
