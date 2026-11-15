"""Container command generator and runtime options builder.

Constructs safe, headless executions adhering to antigravity-sandbox hardening principles
with multi-backend hardware compression (AMD Radeon RX 7000 AV1 / HEVC via VA-API,
NVIDIA NVENC, CPU) and metadata resolution.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from core.config import RecipeConfig
from core.gpu import GPUInfo, detect_gpu


IMAGE_NAME = "antigravity-operator:latest"
REMOTE_IMAGE_NAME = "ghcr.io/retr0xcc/antigravity-operator:latest"
DNS_PRIMARY = "9.9.9.9"
DNS_SECONDARY = "149.112.112.112"


def detect_docker_network() -> str:
    """Detect if isolated agy_net bridge from antigravity-sandbox is available."""
    docker_bin = shutil.which("docker")
    if docker_bin:
        try:
            res = subprocess.run(
                [docker_bin, "network", "inspect", "agy_net"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                return "agy_net"
        except Exception:
            pass
    return "bridge"


def build_agent_prompt(
    recipe_name: str,
    source_subpath: str,
    dest_subpath: str | None,
    mode: str,
    compress: bool,
    remux: bool,
    enable_metadata: bool,
    dry_run: bool,
    auto: bool,
    quality: int = 28,
    preset: str = "p6",
    codec: str = "av1",
    backend: str = "vaapi",
    gpu_name: str = "AMD Radeon RX 7000 (AV1 Hardware Encode)",
    force_hevc: bool = False,
    max_bitrate: int | None = None,
    detected_title: str | None = None,
    detected_year: str | None = None,
    detected_author: str | None = None,
    category: str | None = None,
) -> str:
    """Generate a mode-specific, focused prompt instructing the agent."""
    src_display = f"/storage/{source_subpath}" if source_subpath else "/storage/Downloads"
    dest_display = f"/storage/{dest_subpath}" if dest_subpath else "/storage/Media (Auto-categorized)"

    # Effective operational mode
    effective_mode = mode
    if compress and effective_mode == "link":
        effective_mode = "full" if remux else "compress"
    elif remux and effective_mode == "link":
        effective_mode = "remux"

    force_note = ""
    if force_hevc:
        force_note = f"\n- Force Re-encode:   ENABLED (Re-encode unconditionally via {backend.upper()} {codec.upper()} Quality {quality})."
    if max_bitrate:
        force_note += f"\n- Max Bitrate:       {max_bitrate} kbps threshold (Re-encode files exceeding this bitrate)."

    meta_info = ""
    if detected_title:
        meta_info = f"- Pre-resolved Metadata: '{detected_title}'"
        if detected_year:
            meta_info += f" ({detected_year})"
        if category:
            meta_info += f" [Type: {category.upper()}]"
        if detected_author:
            meta_info += f" [Author: {detected_author}]"
        meta_info += "\n"

    # Plan 1: Fast Link & Cataloging Plan (media-link)
    if effective_mode == "link" or recipe_name == "media-link":
        if dry_run:
            exec_steps = (
                "EXECUTION STEPS (DRY-RUN SIMULATION):\n"
                f"1. Inspect media files in `{src_display}`.\n"
                f"2. Determine canonical destination names in `{dest_display}` matching Plex/Jellyfin convention:\n"
                "   - Movies: /storage/Media/Movies/{Title} ({Year})/{Title} ({Year}).ext\n"
                "   - TV: /storage/Media/TV/{Title} ({Year})/Season {SS}/{Title} S{SS}E{EE}.ext\n"
                "   - Audiobooks: /storage/Media/Books/{Author}/{Title} ({Year})/\n"
                "3. DRY-RUN MODE IS ACTIVE (/storage is mounted read-only): Do NOT create directories or hardlinks.\n"
                "4. Output a clear execution plan table listing each Source File -> Target Destination Hardlink, and explain the structure."
            )
        else:
            exec_steps = (
                "EXECUTION STEPS:\n"
                f"1. Identify media files in `{src_display}`.\n"
                f"2. Create destination directories in `{dest_display}` matching Plex/Jellyfin convention:\n"
                "   - Movies: /storage/Media/Movies/{Title} ({Year})/{Title} ({Year}).ext\n"
                "   - TV: /storage/Media/TV/{Title} ({Year})/Season {SS}/{Title} S{SS}E{EE}.ext\n"
                "   - Audiobooks: /storage/Media/Books/{Author}/{Title} ({Year})/\n"
                "3. Create hardlinks via `os.link`.\n"
                "4. Output execution summary report."
            )
        return (
            f"You are the autonomous Antigravity Media Link Operator executing recipe '{recipe_name}'.\n"
            f"GOAL: Organize media into Plex/Jellyfin library structure using Zero-Copy hardlinks (os.link).\n\n"
            f"Operational Context:\n"
            f"- Storage Root:       /storage\n"
            f"- Source Target:      {src_display}\n"
            f"- Destination Target: {dest_display}\n"
            f"{meta_info}"
            f"- Dry-Run Mode:       {'ENABLED (Simulate only, print planned actions, do NOT modify filesystem)' if dry_run else 'DISABLED'}\n\n"
            f"STRICT RULES:\n"
            f"1. SCRATCH ISOLATION: Working directory is /tmp. NEVER write Python scripts, shell scripts, or temporary files into /storage.\n"
            f"2. ZERO-COPY HARDLINKS: Original torrents in /storage/Downloads must NEVER be deleted, moved, or altered (keep seeding intact). Use os.link(src, dst).\n"
            f"3. NO RE-ENCODING: Do NOT run ffmpeg, do NOT re-encode video, and do NOT launch muxpress.\n\n"
            f"{exec_steps}"
        )

    # Plan 2: Stream Remuxing Plan (media-remux)
    if effective_mode == "remux" or recipe_name == "media-remux":
        if dry_run:
            exec_steps = (
                "EXECUTION STEPS (DRY-RUN SIMULATION):\n"
                f"1. Inspect files in `{src_display}` for video streams, audio tracks (.mka), and subtitles (.ass/.srt).\n"
                "2. DRY-RUN MODE IS ACTIVE (/storage is mounted read-only): Do NOT execute muxpress or write files.\n"
                "3. Print the planned `muxpress` command line and stream layout table.\n"
                "4. Print summary plan."
            )
        else:
            exec_steps = (
                "EXECUTION STEPS:\n"
                f"1. Identify media files in `{src_display}`.\n"
                "2. PRESERVE TORRENTS: Downloads in /storage/Downloads must remain completely untouched.\n"
                "3. USE MUXPRESS CLI: Execute remuxing using the built-in CLI command:\n"
                f"   `muxpress \"{src_display}\" --output-dir \"{dest_display}\" --merge-only`\n"
                "   (Lossless stream copy -c copy with fonts attached, no re-encoding).\n"
                "4. Print summary report."
            )
        return (
            f"You are the autonomous Antigravity Media Remux Operator executing recipe '{recipe_name}'.\n"
            f"GOAL: Merge video, companion audio tracks (.mka/.ac3), subtitles (.ass/.srt), and fonts into single MKV containers.\n\n"
            f"Operational Context:\n"
            f"- Storage Root:       /storage\n"
            f"- Source Target:      {src_display}\n"
            f"- Destination Target: {dest_display}\n"
            f"{meta_info}"
            f"- Dry-Run Mode:       {'ENABLED (Simulate only, print planned actions, do NOT modify filesystem)' if dry_run else 'DISABLED'}\n\n"
            f"STRICT RULES:\n"
            f"1. SCRATCH ISOLATION: Working directory is /tmp. NEVER write custom Python or shell scripts into /storage.\n"
            f"2. PRESERVE TORRENTS: Downloads in /storage/Downloads must remain completely untouched.\n"
            f"3. USE MUXPRESS CLI: Execute remuxing using the built-in CLI command:\n"
            f"   `muxpress \"{src_display}\" --output-dir \"{dest_display}\" --merge-only`\n"
            f"   (Lossless stream copy -c copy with fonts attached, no re-encoding).\n"
            f"{exec_steps}"
        )

    # Plan 3: Hardware Compression Plan (media-compress)
    if effective_mode == "compress" or recipe_name == "media-compress":
        force_flag = " --force-reencode" if force_hevc else ""
        if dry_run:
            exec_steps = (
                "EXECUTION STEPS (DRY-RUN SIMULATION):\n"
                f"1. Probe files in `{src_display}` to detect existing codecs, bitrates, and resolutions.\n"
                "2. DRY-RUN MODE IS ACTIVE (/storage is mounted read-only): Do NOT run ffmpeg/muxpress compression.\n"
                "3. Print the exact compression command that would be executed and estimated bitrate reduction.\n"
                "4. Print simulation summary."
            )
        else:
            exec_steps = (
                "EXECUTION STEPS:\n"
                f"1. Probe files in `{src_display}` to verify existing codec and bitrate.\n"
                "2. USE MUXPRESS CLI: Do NOT invent custom ffmpeg scripts from scratch. Run the built-in Muxpress command:\n"
                f"   `muxpress \"{src_display}\" --compress-only --backend {backend} --codec {codec} --quality {quality}{force_flag}`\n"
                "3. ATOMIC ROLLBACK: Muxpress automatically checks if the re-encoded file is larger and rolls back.\n"
                "4. Print summary report of bytes saved."
            )
        return (
            f"You are the autonomous Antigravity Media Compression Operator executing recipe '{recipe_name}'.\n"
            f"GOAL: Hardware {backend.upper()} {codec.upper()} compression ({gpu_name}) with atomic rollback protection.\n\n"
            f"Operational Context:\n"
            f"- Storage Root:       /storage\n"
            f"- Source Target:      {src_display}\n"
            f"- Hardware Encoder:   {gpu_name} [{backend.upper()}]\n"
            f"- Target Codec:       {codec.upper()} (Quality {quality}, preset {preset})\n"
            f"{force_note}\n"
            f"- Dry-Run Mode:       {'ENABLED (Simulate only, print planned actions, do NOT modify filesystem)' if dry_run else 'DISABLED'}\n\n"
            f"STRICT RULES:\n"
            f"1. SCRATCH ISOLATION: Working directory is /tmp. NEVER create scratch .py scripts in /storage.\n"
            f"2. USE MUXPRESS CLI: Do NOT invent custom ffmpeg scripts from scratch. Run the built-in Muxpress command:\n"
            f"   `muxpress \"{src_display}\" --compress-only --backend {backend} --codec {codec} --quality {quality}{force_flag}`\n"
            f"3. ATOMIC ROLLBACK: Muxpress automatically checks if the re-encoded file is larger and rolls back.\n"
            f"{exec_steps}"
        )

    # Plan 4: Full Multi-Stage Pipeline (media-pipeline)
    if dry_run:
        exec_steps = (
            "EXECUTION STEPS (DRY-RUN SIMULATION):\n"
            f"1. Inspect `{src_display}` and determine needed stages (Link, Remux, Compress).\n"
            "2. DRY-RUN MODE IS ACTIVE (/storage is mounted read-only): Do NOT modify storage.\n"
            "3. Print the complete multi-stage execution plan.\n"
            "4. Print simulation summary."
        )
    else:
        exec_steps = (
            "EXECUTION STEPS:\n"
            f"1. Identify media files in `{src_display}`.\n"
            "2. Use the built-in CLI tool `muxpress` for remux and compression:\n"
            f"   `muxpress \"{src_display}\" --output-dir \"{dest_display}\" --backend {backend} --codec {codec} --quality {quality}`\n"
            "3. Print summary report upon completion."
        )
    return (
        f"You are the autonomous Antigravity Media Operator executing recipe '{recipe_name}'.\n"
        f"Follow SOP procedures in /recipe/INSTRUCTIONS.md.\n\n"
        f"Operational Context:\n"
        f"- Common Storage Root: /storage\n"
        f"- Source Target:      {src_display}\n"
        f"- Destination Target: {dest_display}\n"
        f"- Pipeline Mode:      {effective_mode.upper()} [link | remux | compress | full]\n"
        f"- Remux to Single MKV:{'ENABLED' if (remux or effective_mode in ('remux', 'full')) else 'DISABLED'}\n"
        f"- Video Compression:  {'ENABLED (' + gpu_name + ' ' + backend.upper() + ' ' + codec.upper() + ', Quality ' + str(quality) + ')' if (compress or effective_mode in ('compress', 'full')) else 'DISABLED'}"
        f"{force_note}\n"
        f"{meta_info}"
        f"- Metadata Search:    {'ENABLED (Query IMDb/Wikipedia/Cyclopedia for canonical Title, Year, Author)' if enable_metadata else 'OFFLINE (Use local regex cleaning)'}\n"
        f"- Dry-Run Mode:       {'ENABLED (Simulate only, print planned actions, do NOT modify filesystem)' if dry_run else 'DISABLED'}\n\n"
        f"STRICT RULES:\n"
        f"1. SCRATCH ISOLATION: Working directory is /tmp. NEVER write helper scripts or scratch files into /storage.\n"
        f"2. Original torrents in /storage/Downloads must NEVER be deleted, moved, or altered.\n"
        f"3. Use the built-in CLI tool `muxpress` for remux and compression:\n"
        f"   `muxpress \"{src_display}\" --output-dir \"{dest_display}\" --backend {backend} --codec {codec} --quality {quality}`\n"
        f"{exec_steps}"
    )


def build_docker_cmd(
    recipe: RecipeConfig,
    storage_root: Path,
    source_subpath: str = "",
    dest_subpath: str | None = None,
    mode: str = "link",
    compress: bool = False,
    remux: bool = False,
    enable_metadata: bool = True,
    offline: bool = False,
    proxy_port: int | None = None,
    proxy_socket_path: str | Path | None = None,
    dry_run: bool = False,
    auto: bool = False,
    quality: int = 28,
    preset: str = "p6",
    codec: str = "av1",
    backend: str = "vaapi",
    gpu_info: GPUInfo | None = None,
    device_path: str | None = None,
    force_hevc: bool = False,
    max_bitrate: int | None = None,
    stream: bool = True,
    interactive_tui: bool = False,
    extra_docker_args: Sequence[str] = (),
    detected_title: str | None = None,
    detected_year: str | None = None,
    detected_author: str | None = None,
    category: str | None = None,
    image_name: str | None = None,
    api_key: str | None = None,
) -> list[str]:
    """Build the complete 'docker run' argument list."""
    gpu = gpu_info or detect_gpu()
    cmd: list[str] = ["docker", "run", "--rm"]

    # Interactive / TTY flags
    if interactive_tui:
        cmd.extend(["-it"])
    else:
        cmd.extend(["-i"])

    # Hardening & system limits (synchronized with antigravity-sandbox)
    cmd.extend([
        "--init",
        "--security-opt=no-new-privileges:true",
        "--cap-drop=NET_RAW",
        "--sysctl=net.ipv6.conf.all.disable_ipv6=1",
        "--sysctl=net.ipv6.conf.default.disable_ipv6=1",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=4g,mode=1777",
        "-w", "/tmp",
    ])

    # Resource constraints from recipe
    res = recipe.resources
    if "pids" in res:
        cmd.append(f"--pids-limit={res['pids']}")
    if "memory" in res:
        cmd.append(f"--memory={res['memory']}")
    if "cpus" in res:
        cmd.append(f"--cpus={res['cpus']}")

    # Network & DNS configuration
    if offline:
        cmd.append("--network=none")
    elif proxy_socket_path:
        cmd.extend([
            "--network=none",
            "-v", f"{Path(proxy_socket_path).resolve()}:/run/proxy.sock",
            "-e", "HTTP_PROXY=http://127.0.0.1:3128",
            "-e", "HTTPS_PROXY=http://127.0.0.1:3128",
            "-e", "http_proxy=http://127.0.0.1:3128",
            "-e", "https_proxy=http://127.0.0.1:3128",
            "-e", "ALL_PROXY=http://127.0.0.1:3128",
            "-e", "all_proxy=http://127.0.0.1:3128",
            "-e", "NO_PROXY=localhost,127.0.0.1",
            "-e", "no_proxy=localhost,127.0.0.1",
        ])
    else:
        net_name = detect_docker_network()
        cmd.extend([
            f"--network={net_name}",
            f"--dns={DNS_PRIMARY}",
            f"--dns={DNS_SECONDARY}",
        ])
        if proxy_port:
            cmd.extend([
                "--add-host=host.docker.internal:host-gateway",
                "-e", f"HTTP_PROXY=http://host.docker.internal:{proxy_port}",
                "-e", f"HTTPS_PROXY=http://host.docker.internal:{proxy_port}",
                "-e", f"http_proxy=http://host.docker.internal:{proxy_port}",
                "-e", f"https_proxy=http://host.docker.internal:{proxy_port}",
                "-e", f"ALL_PROXY=http://host.docker.internal:{proxy_port}",
                "-e", f"all_proxy=http://host.docker.internal:{proxy_port}",
                "-e", "NO_PROXY=localhost,127.0.0.1",
                "-e", "no_proxy=localhost,127.0.0.1",
            ])

    # Hardware acceleration passthrough (AMD VA-API / NVIDIA NVENC / Intel)
    is_compression_active = compress or mode in ("compress", "full") or recipe.gpu_default
    if is_compression_active:
        if backend == "vaapi" or gpu.vendor in ("amd", "intel"):
            # Pass DRI device node to container
            cmd.extend([
                "--device=/dev/dri:/dev/dri",
                "--group-add=video",
                "--group-add=render",
            ])
            if os.path.exists("/dev/kfd"):
                cmd.append("--device=/dev/kfd")
        elif backend == "nvenc" or gpu.vendor == "nvidia":
            cmd.extend(["--gpus", "all"])

    # 1. Mount Common Storage Root (Strict :rw for hardlinks across Downloads and Media; :ro during dry-run simulation)
    storage_access = "ro" if dry_run else "rw"
    cmd.extend(["-v", f"{storage_root.resolve()}:/storage:{storage_access}"])

    # 2. Mount Recipe and Recipes Directory (Strict Read-Only :ro)
    recipes_parent = recipe.path.parent
    cmd.extend([
        "-v", f"{recipes_parent.resolve()}:/recipes:ro",
        "-v", f"{recipe.path.resolve()}:/recipe:ro",
    ])

    # 3. Mount persistent Gemini auth and tool cache Docker volumes
    # Keeps auth state fully inside container volumes without requiring Antigravity on host
    cmd.extend([
        "-v", "agy-operator-config:/home/agent/.gemini",
        "-v", "agy-operator-cache:/home/agent/.cache",
    ])

    # Pass Gemini / Google API Key if provided or available in host environment
    effective_api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if effective_api_key:
        cmd.extend([
            "-e", f"GEMINI_API_KEY={effective_api_key}",
            "-e", f"GOOGLE_API_KEY={effective_api_key}",
        ])

    # Pass environment variables for scripts inside container
    dev_path = device_path or gpu.device_path or "/dev/dri/renderD128"
    cmd.extend([
        "-e", "TMPDIR=/tmp",
        "-e", "TINI_SUBREAPER=1",
        "-e", f"OPERATE_MODE={mode}",
        "-e", f"OPERATE_DRY_RUN={'1' if dry_run else '0'}",
        "-e", f"OPERATE_COMPRESS={'1' if is_compression_active else '0'}",
        "-e", f"OPERATE_FORCE_HEVC={'1' if force_hevc else '0'}",
        "-e", f"OPERATE_FORCE_REENCODE={'1' if force_hevc else '0'}",
        "-e", f"OPERATE_MAX_BITRATE={str(max_bitrate or '')}",
        "-e", f"OPERATE_REMUX={'1' if (remux or mode in ('remux', 'full')) else '0'}",
        "-e", f"OPERATE_METADATA={'1' if enable_metadata else '0'}",
        "-e", f"OPERATE_OFFLINE={'1' if offline else '0'}",
        "-e", f"OPERATE_AUTO={'1' if auto else '0'}",
        "-e", f"OPERATE_SOURCE_SUBPATH={source_subpath}",
        "-e", f"OPERATE_DEST_SUBPATH={dest_subpath or ''}",
        "-e", f"OPERATE_GPU_BACKEND={backend}",
        "-e", f"OPERATE_VIDEO_CODEC={codec}",
        "-e", f"OPERATE_DRI_DEVICE={dev_path}",
        "-e", f"OPERATE_QUALITY={quality}",
        "-e", f"OPERATE_NVENC_QP={quality}",
        "-e", f"OPERATE_NVENC_PRESET={preset}",
    ])

    # Append any extra docker arguments
    cmd.extend(extra_docker_args)

    # Image
    cmd.append(image_name or IMAGE_NAME)

    # Determine reasoning effort based on task complexity
    effective_mode = mode
    if is_compression_active and effective_mode == "link":
        effective_mode = "full" if remux else "compress"
    elif remux and effective_mode == "link":
        effective_mode = "remux"

    effort_level = "low" if effective_mode == "link" else ("medium" if effective_mode == "remux" else "high")

    # Command executed in container: agy headless runner
    agent_prompt = build_agent_prompt(
        recipe_name=recipe.name,
        source_subpath=source_subpath,
        dest_subpath=dest_subpath,
        mode=mode,
        compress=is_compression_active,
        remux=remux,
        enable_metadata=enable_metadata,
        dry_run=dry_run,
        auto=auto,
        quality=quality,
        preset=preset,
        codec=codec,
        backend=backend,
        gpu_name=gpu.name,
        force_hevc=force_hevc,
        max_bitrate=max_bitrate,
        detected_title=detected_title,
        detected_year=detected_year,
        detected_author=detected_author,
        category=category,
    )

    agy_args: list[str] = [
        "agy",
        "--dangerously-skip-permissions",
        "--effort", effort_level,
    ]

    # Explicitly activate Gemini API mode in agy when an API key is present
    if effective_api_key:
        agy_args.append('--settings={"modelProvider":"gemini"}')

    if interactive_tui:
        agy_args.append(f"-i={agent_prompt}")
    elif stream:
        agy_args.extend([
            "--output-format", "stream-json",
            "--print-timeout=0",
            f"-p={agent_prompt}",
        ])
    else:
        agy_args.extend([
            "--print-timeout=0",
            f"--print={agent_prompt}",
        ])

    if proxy_socket_path:
        cmd.extend([
            "sh", "-c",
            'socat TCP-LISTEN:3128,bind=127.0.0.1,fork,reuseaddr UNIX-CONNECT:/run/proxy.sock & sleep 0.05; exec "$@"',
            "--",
        ])

    cmd.extend(agy_args)
    return cmd
