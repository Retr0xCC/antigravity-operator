"""Launcher module for running Antigravity Media Operator planning inside SBX.

Prepares host hardware profile, provisions workspace and output directories,
mounts media strictly in Read-Only (:ro) mode via native Docker Sandboxes (sbx)
positional workspaces, and dispatches the planning agent.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from core.gpu import detect_gpu


DEFAULT_BASE_AGENT = "shell"
DEFAULT_BASE_KIT = "ghcr.io/retr0xcc/antigravity-kit:latest"
DEFAULT_MIXIN_KIT = "ghcr.io/retr0xcc/media-operator-kit:latest"
DEFAULT_OPERATOR_IMAGE = "ghcr.io/retr0xcc/antigravity-operator:latest"
FALLBACK_SBX_IMAGE = "ghcr.io/retr0xcc/antigravity-sbx-patched:latest"


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


def write_host_profile(target_dir: Path, profile: dict) -> Path:
    """Save host_profile.json in the specified directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    profile_path = target_dir / "host_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return profile_path


def resolve_base_kit_path() -> str:
    """Find local base antigravity kit directory or fallback to remote OCI reference."""
    repo_root = Path(__file__).resolve().parent.parent
    neighbor_base = repo_root.parent / "antigravity-sbx-patched" / "kits" / "antigravity"
    if neighbor_base.is_dir() and (neighbor_base / "spec.yaml").is_file():
        return str(neighbor_base.resolve())
    return DEFAULT_BASE_KIT


def resolve_kit_path() -> str:
    """Find local media-operator mixin kit directory or fallback to remote OCI reference."""
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


def get_effective_image(custom_image: str | None = None) -> str:
    """Find the best available image with media tools (ffprobe, mkvmerge, agy)."""
    if custom_image:
        return custom_image

    docker_bin = shutil.which("docker")
    if not docker_bin:
        return DEFAULT_OPERATOR_IMAGE

    for candidate in [
        "antigravity-operator:latest",
        DEFAULT_OPERATOR_IMAGE,
        "ghcr.io/retr0xcc/media-operator:latest",
        FALLBACK_SBX_IMAGE,
    ]:
        try:
            res = subprocess.run(
                [docker_bin, "image", "inspect", candidate],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                return candidate
        except Exception:
            pass

    return DEFAULT_OPERATOR_IMAGE


def run_sandbox_planner(
    source_dir: Path | str,
    dest_dir: Path | str,
    out_dir: Path | str,
    mode: str = "link",
    quality: int = 28,
    max_bitrate: int | None = None,
    force_reencode: bool = False,
    headless: bool = False,
    custom_image: str | None = None,
    base_kit_ref: str | None = None,
    mixin_kit_ref: str | None = None,
) -> tuple[int, Path | None]:
    """Launch the read-only sandbox planner using Docker Sandboxes (sbx) to generate plan.json.

    Architecture:
      - Primary Workspace: <workspace> (RW) containing AGENTS.md and host_profile.json
      - Extra Output Mount: <out>:/media/output (RW) for plan.json, summary.md, apply.sh
      - Extra Input Mount:  <source>:/media/input:ro (strict RO hardware protection)

    Returns:
        (returncode, plan_json_path or None)
    """
    src = Path(source_dir).resolve()
    dst = Path(dest_dir).resolve()
    out = Path(out_dir).resolve()
    workspace = out.parent / "workspace"

    if not src.exists():
        print(f"[-] Source directory does not exist: {src}", file=sys.stderr)
        return 1, None

    out.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)

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
    write_host_profile(workspace, profile)

    # 2. Resolve Kits and copy AGENTS.md instructions
    eff_base_agent = base_kit_ref or DEFAULT_BASE_AGENT
    eff_mixin_kit = mixin_kit_ref or resolve_kit_path()
    eff_image = get_effective_image(custom_image)

    kit_path = Path(eff_mixin_kit)
    if kit_path.is_dir() and (kit_path / "AGENTS.md").is_file():
        shutil.copy2(kit_path / "AGENTS.md", workspace / "AGENTS.md")
        shutil.copy2(kit_path / "AGENTS.md", out / "AGENTS.md")

    # 3. Detect Sandbox Runner (sbx preferred, docker engine fallback)
    sbx_bin = shutil.which("sbx")
    docker_bin = shutil.which("docker")

    if not sbx_bin and not docker_bin:
        print("[-] Neither 'sbx' (Docker Sandboxes) nor 'docker' engine found in PATH.", file=sys.stderr)
        return 1, None

    initial_prompt = (
        "Inspect all files in /media/input and generate /media/output/plan.json, "
        "/media/output/summary.md, and /media/output/apply.sh strictly according to "
        "/media/output/host_profile.json and your AGENTS.md instructions."
    )
    prompt_flag = f"--prompt={initial_prompt}" if headless else f"--prompt-interactive={initial_prompt}"

    print("=" * 72)
    print("  Antigravity Media Operator: Read-Only Planning Sandbox (SBX)")
    print("=" * 72)
    print(f"  Source (Read-Only): {src}")
    print(f"  Target Destination: {dst}")
    print(f"  Workspace Dir:      {workspace}")
    print(f"  Plan Output Dir:    {out}")
    print(f"  Operating Mode:     {mode.upper()}")
    print(f"  Host GPU:           {profile['gpu']['name']} ({profile['gpu']['backend'].upper()})")
    print(f"  Sandbox Runner:     {'Docker Sandboxes (sbx)' if sbx_bin else 'Docker Engine (fallback)'}")
    print(f"  Base Agent:         {eff_base_agent}")
    print(f"  Mixin Kit:          {eff_mixin_kit}")
    print(f"  Execution Mode:     {'Headless (Auto-exit)' if headless else 'Interactive TUI'}")
    print("=" * 72 + "\n")

    if sbx_bin:
        # Clean any dangling container with same name before starting
        subprocess.run(
            [sbx_bin, "rm", "-f", "agy-media-planner"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        cmd = [
            sbx_bin, "run",
            "--rm",
            "--name", "agy-media-planner",
            "--template", eff_image,
            "--kit", eff_mixin_kit,
        ]

        # Pass API keys if present in host environment
        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if os.environ.get(key):
                cmd.extend(["-e", key])

        # Positional arguments: [SANDBOX_KIT] [PRIMARY_WORKSPACE] [EXTRA_WORKSPACES...]
        cmd.extend([
            eff_base_agent,
            str(workspace),
            f"{out}:/media/output",
            f"{src}:/media/input:ro",
            "--",
        ])

        if eff_base_agent == "shell":
            agy_cmd = f"exec agy --dangerously-skip-permissions {shlex.quote(prompt_flag)}"
            cmd.extend(["-l", "-c", agy_cmd])
        else:
            cmd.extend(["--dangerously-skip-permissions", prompt_flag])
    else:
        # Fallback to direct Docker if sbx is not installed
        is_tty = sys.stdin.isatty() and sys.stdout.isatty()
        cmd = [
            docker_bin, "run",
            "--rm",
            "--name", "agy-media-planner",
            "-w", "/media/output",
            "-v", f"{src}:/media/input:ro",
            "-v", f"{out}:/media/output:rw",
        ]

        if not headless and is_tty:
            cmd.insert(2, "-it")
        elif not headless:
            cmd.insert(2, "-i")

        host_gemini = Path(os.environ.get("GEMINI_HOME", Path.home() / ".gemini")).resolve()
        if host_gemini.is_dir():
            cmd.extend(["-v", f"{host_gemini}:/home/agent/.gemini"])

        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            val = os.environ.get(key)
            if val:
                cmd.extend(["-e", f"{key}={val}"])

        cmd.extend([
            eff_image,
            "agy",
            "--dangerously-skip-permissions",
            prompt_flag,
        ])

    try:
        res = subprocess.run(cmd)
        ret = res.returncode
    except KeyboardInterrupt:
        print("\n[!] Planning aborted by user.")
        return 130, None
    except Exception as e:
        print(f"[-] Sandbox execution error: {e}", file=sys.stderr)
        return 1, None

    # Sync any artifacts saved directly in workspace to out
    for fname in ("plan.json", "summary.md", "apply.sh"):
        ws_file = workspace / fname
        out_file = out / fname
        if ws_file.is_file() and not out_file.is_file():
            try:
                shutil.copy2(ws_file, out_file)
            except Exception:
                pass

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

    plan_json = out / "plan.json"
    if plan_json.is_file() and plan_json.stat().st_size > 0:
        return ret, plan_json
    return ret, None
