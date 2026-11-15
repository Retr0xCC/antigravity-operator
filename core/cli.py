"""CLI Interface and argument parser for antigravity-operator."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from core.config import list_recipes, load_recipe, RecipeError
from core.container import build_docker_cmd, IMAGE_NAME, REMOTE_IMAGE_NAME
from core.gpu import detect_gpu
from core.metadata import clean_title_tokens, search_imdb, search_cyclopedia_book
from core.proxy import EphemeralAllowlistProxy
from core.runner import execute_container
from core.security import resolve_storage_boundaries, SecurityError


REPO_ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = REPO_ROOT / "recipes"
DOCKERFILE_PATH = REPO_ROOT / "docker" / "Dockerfile"


def check_image_exists(image_name: str) -> bool:
    """Check if the specified Docker image is present locally."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run(
            [docker_bin, "image", "inspect", image_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0
    except Exception:
        return False


def get_effective_image_name() -> str:
    """Find the best available image: local tag first, then remote published tag."""
    for img in (IMAGE_NAME, REMOTE_IMAGE_NAME):
        if check_image_exists(img):
            return img
    return REMOTE_IMAGE_NAME


def check_auth_available(api_key: str | None = None) -> tuple[bool, str]:
    """Check whether Gemini authentication (OAuth token or API key) is available on the host."""
    eff_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if eff_key:
        return True, "API Key (GEMINI_API_KEY / GOOGLE_API_KEY)"

    token_file = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    if token_file.is_file() and token_file.stat().st_size > 0:
        return True, f"OAuth Token (~/.gemini/.../antigravity-oauth-token)"

    return False, "None"


def cmd_list(args: argparse.Namespace) -> int:
    """List available recipes."""
    recipes = list_recipes(RECIPES_DIR)
    if not recipes:
        print("No recipes found in 'recipes/' directory.")
        return 0

    print("Available recipes:")
    print("=" * 78)
    for r in recipes:
        gpu_badge = "[GPU Required]" if r.gpu_default else "[GPU Optional]"
        net_badge = "[Net: On]" if r.network_default else "[Net: Isolated]"
        print(f"  • {r.name:<18} v{r.version:<6} {gpu_badge:<15} {net_badge}")
        print(f"    Description: {r.description}")
        print(f"    Timeout:     {r.timeout} | Memory: {r.resources.get('memory', 'default')}")
        print("-" * 78)

    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run a specified recipe against source and destination media storage."""
    recipe_name = args.recipe
    source_raw = args.source
    dest_raw = args.destination or args.dest

    try:
        recipe = load_recipe(RECIPES_DIR, recipe_name)
    except RecipeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        storage_root, src_subpath, dest_subpath = resolve_storage_boundaries(
            source_path=source_raw,
            dest_path=dest_raw,
        )
    except SecurityError as e:
        print(f"Security Error: {e}", file=sys.stderr)
        return 1

    # Detect Host GPU Acceleration capabilities
    gpu = detect_gpu()

    # Codec, backend, device and quality resolution
    force_reencode = bool(getattr(args, "force_reencode", False) or getattr(args, "force_hevc", False))
    max_bitrate = getattr(args, "max_bitrate", None)
    compress_active = args.compress or force_reencode or (max_bitrate is not None)

    codec = args.codec if args.codec != "auto" else gpu.recommended_codec
    backend = args.backend if args.backend != "auto" else gpu.backend
    quality = getattr(args, "quality", None) or getattr(args, "qp", 28)
    device_path = args.device or gpu.device_path

    # Determine effective mode (inherit from recipe if specific)
    mode = args.mode
    if recipe.name == "media-link":
        mode = "link"
    elif recipe.name == "media-remux":
        mode = "remux"
        args.remux = True
    elif recipe.name == "media-compress":
        mode = "compress"
        compress_active = True
    else:
        if compress_active and mode == "link":
            mode = "full" if args.remux else "compress"
        elif args.remux and mode == "link":
            mode = "remux"

    # Metadata resolution preview (IMDb / Wikipedia / Cyclopedia)
    is_offline = bool(getattr(args, "offline", False))
    use_proxy = not is_offline and not bool(getattr(args, "no_proxy", False))
    metadata_enabled = not is_offline
    detected_title = None
    detected_year = None
    detected_author = None

    src_name = Path(source_raw).name
    clean_t, clean_y, cat = clean_title_tokens(src_name)

    if metadata_enabled:
        print(f"==> Querying online metadata for '{src_name}'...")
        if cat == "book":
            detected_author, detected_title, detected_year = search_cyclopedia_book(clean_t)
            print(f"    [Book Metadata] Author: {detected_author} | Title: {detected_title} ({detected_year or 'N/A'})")
        else:
            detected_title, detected_year = search_imdb(clean_t, clean_y)
            print(f"    [IMDb/Wiki Metadata] Canonical: '{detected_title}' ({detected_year or 'Unknown'}) [{cat.upper()}]")
    else:
        detected_title = clean_t
        detected_year = clean_y

    is_in_place_media = "Media" in src_subpath

    # Verify authentication credentials (unless running strictly offline)
    cli_api_key = getattr(args, "api_key", None)
    has_auth, auth_type = check_auth_available(cli_api_key)
    if not has_auth and not is_offline:
        print("\n[-] Error: Google Antigravity authentication required.", file=sys.stderr)
        print("    No active OAuth credentials or GEMINI_API_KEY found on this host.\n", file=sys.stderr)
        print("    To authenticate, please do one of the following:", file=sys.stderr)
        print("    1. Sign in interactively with your Google account:", file=sys.stderr)
        print("       bin/operate login\n", file=sys.stderr)
        print("    2. Or provide a Gemini API key:", file=sys.stderr)
        print("       export GEMINI_API_KEY=\"your-gemini-api-key\"", file=sys.stderr)
        print("       (or pass: bin/operate run ... --api-key=\"your-api-key\")\n", file=sys.stderr)
        return 1

    # Start local allowlist proxy for domain filtering and LAN protection
    proxy = None
    proxy_port = None
    if use_proxy:
        proxy = EphemeralAllowlistProxy(bind_host="0.0.0.0")
        proxy_port = proxy.start()

    print(f"==> Launching Antigravity Operator [{recipe.name}]")
    print(f"    Runtime Engine: Docker Container")
    print(f"    Storage Root:   {storage_root} (mounted to /storage:{'ro' if args.dry_run else 'rw'})")
    print(f"    Source Target:  /storage/{src_subpath}" if src_subpath else "    Source Target:  /storage/Downloads")
    if dest_subpath:
        print(f"    Dest Target:    /storage/{dest_subpath}")
    elif is_in_place_media:
        print(f"    Dest Target:    In-place (/storage/{src_subpath})")
    else:
        print(f"    Dest Target:    /storage/Media/{cat.capitalize()} (Auto-categorized)")

    print(f"    Pipeline Mode:  {mode.upper()} (remux: {args.remux}, compress: {compress_active})")
    print(f"    Hardlink Mode:  Shared ext4 partition (EXDEV safe, original torrents seeding)")
    print(f"    Authentication: {auth_type if not is_offline else 'Offline (no API required)'}")

    if compress_active or mode in ("compress", "full"):
        av1_badge = " [AV1 Hardware Encode]" if gpu.supports_av1 else ""
        print(f"    GPU Accelerator:{gpu.name} [{backend.upper()}]{av1_badge}")
        print(f"    Target Codec:   {codec.upper()} (Quality/QP: {quality}, Preset: {args.preset})")
        if device_path and backend == "vaapi":
            print(f"    DRI Device:     {device_path}")
    else:
        print(f"    GPU Accelerator:Disabled (Lossless / Zero-CPU mode)")

    if force_reencode:
        print(f"    Force Re-encode:YES (Re-encode unconditionally)")
    if max_bitrate:
        print(f"    Max Bitrate:    {max_bitrate} kbps threshold")
    print(f"    Metadata Search:{'Enabled (IMDb / Wiki / Cyclopedia)' if metadata_enabled else 'Offline (regex cleaning only)'}")

    if is_offline:
        print("    Network:        none (Airgapped / Isolated, no external or LAN access)")
    elif use_proxy:
        from core.container import detect_docker_network
        net_name = detect_docker_network()
        print(f"    Network:        {net_name} (Egress Allowlist Proxy on :{proxy_port}, LAN Isolated)")
    else:
        from core.container import detect_docker_network, DNS_PRIMARY, DNS_SECONDARY
        net_name = detect_docker_network()
        print(f"    Network:        {net_name} (Direct unproxied, Dual-DNS: {DNS_PRIMARY}, {DNS_SECONDARY})")
    print(f"    Dry Run:        {'YES (simulation only)' if args.dry_run else 'NO (live execution)'}")
    print(f"    Unattended:     {'YES' if args.auto else 'NO'}")
    print("=" * 78)

    use_interactive_tui = bool(getattr(args, "interactive", False))
    use_stream = not bool(getattr(args, "no_stream", False)) and not use_interactive_tui

    try:
        eff_image = get_effective_image_name()
        cmd = build_docker_cmd(
            recipe=recipe,
            storage_root=storage_root,
            source_subpath=src_subpath,
            dest_subpath=dest_subpath,
            mode=mode,
            compress=compress_active,
            remux=args.remux,
            enable_metadata=metadata_enabled,
            offline=is_offline,
            proxy_port=proxy_port,
            dry_run=args.dry_run,
            auto=args.auto,
            quality=quality,
            preset=args.preset,
            codec=codec,
            backend=backend,
            gpu_info=gpu,
            device_path=device_path,
            force_hevc=force_reencode,
            max_bitrate=max_bitrate,
            stream=use_stream,
            interactive_tui=use_interactive_tui,
            detected_title=detected_title,
            detected_year=detected_year,
            detected_author=detected_author,
            category=cat,
            image_name=eff_image,
            api_key=cli_api_key,
        )

        image_ready = check_image_exists(eff_image)

        if not image_ready:
            print(f"==> Image '{eff_image}' not found locally. Attempting to pull from registry...")
            docker_bin = shutil.which("docker") or "docker"
            try:
                res = subprocess.run([docker_bin, "pull", eff_image])
                if res.returncode == 0:
                    image_ready = True
                else:
                    print(f"[-] Remote pull failed (image '{eff_image}' not yet published or private).", file=sys.stderr)
            except Exception as e:
                print(f"[-] Pull attempt failed: {e}", file=sys.stderr)

        if not image_ready:
            print(f"\nError: Container image '{eff_image}' not found locally or in registry.", file=sys.stderr)
            print("Please build the image first by running:", file=sys.stderr)
            print("    bin/operate build\n", file=sys.stderr)
            return 1

        if args.dry_run:
            print("\n[DRY RUN] Generated Docker execution command:")
            escaped_cmd = [shlex.quote(c) for c in cmd]
            print(" \\\n    ".join(escaped_cmd))
            print("\n[DRY RUN] Launching agent in simulation mode (OPERATE_DRY_RUN=1, /storage:ro)...")
            print("[DRY RUN] The agent will inspect files and output the execution plan without modifying storage.\n")

        return execute_container(cmd, stream=use_stream)
    finally:
        if proxy:
            proxy.stop()


def cmd_build(args: argparse.Namespace) -> int:
    """Build the operator Docker image downstream from antigravity-sbx-patched."""
    if not DOCKERFILE_PATH.is_file():
        print(f"Error: Dockerfile not found at {DOCKERFILE_PATH}", file=sys.stderr)
        return 1

    docker_bin = shutil.which("docker")
    if not docker_bin:
        print("Error: 'docker' binary not found in PATH.", file=sys.stderr)
        return 127

    base_image = getattr(args, "base_image", None) or os.environ.get(
        "BASE_IMAGE", "ghcr.io/retr0xcc/antigravity-sbx-patched:latest"
    )

    print(f"==> Building Docker image '{IMAGE_NAME}' & '{REMOTE_IMAGE_NAME}' (Base: {base_image})...")
    cmd = [
        "docker", "build",
        "-t", IMAGE_NAME,
        "-t", REMOTE_IMAGE_NAME,
        "--build-arg", f"BASE_IMAGE={base_image}",
        "-f", str(DOCKERFILE_PATH),
        str(REPO_ROOT),
    ]

    try:
        res = subprocess.run(cmd)
        return res.returncode
    except Exception as e:
        print(f"Failed to build image: {e}", file=sys.stderr)
        return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check host system readiness for running antigravity-operator."""
    print("==> Checking Antigravity Operator Host Environment...")
    all_ok = True

    # 1. Container Engine Check (Docker)
    docker_bin = shutil.which("docker")
    if docker_bin:
        try:
            v = subprocess.check_output([docker_bin, "--version"], text=True).strip()
            print(f"  [✓] Docker Engine: {v}")
        except Exception:
            print("  [✗] Docker Engine: present but failed to execute.")
            all_ok = False
    else:
        print("  [✗] Docker Engine: NOT FOUND. Please install Docker.")
        all_ok = False

    # 2. Hardware and GPU Acceleration Check
    gpu = detect_gpu()
    if gpu.is_hardware:
        av1_badge = " [AV1 Hardware Encode: Supported]" if gpu.supports_av1 else ""
        print(f"  [✓] Hardware GPU: {gpu.name} ({gpu.backend.upper()}){av1_badge}")
        if gpu.device_path:
            print(f"      DRI Device:   {gpu.device_path}")
        print(f"      Codecs:       {', '.join(c.upper() for c in gpu.supported_codecs)} (Default: {gpu.recommended_codec.upper()})")
    else:
        print(f"  [-] Hardware GPU: None detected. Software encoding fallback will be used ({gpu.recommended_encoder}).")

    # 3. Multimedia tools check
    vainfo = shutil.which("vainfo")
    if vainfo:
        print(f"  [✓] Host VA-API tools: {vainfo}")
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        print(f"  [✓] Host FFmpeg: {ffmpeg_bin}")
    else:
        print("  [-] Host FFmpeg: not on host (container provides isolated ffmpeg/vaapi/nvenc).")

    # 4. Recipes catalog check
    if RECIPES_DIR.is_dir():
        recipes = list_recipes(RECIPES_DIR)
        print(f"  [✓] Recipes Catalog: {len(recipes)} valid recipe(s) loaded from {RECIPES_DIR}")
    else:
        print(f"  [✗] Recipes Directory: missing {RECIPES_DIR}")
        all_ok = False

    # 5. Operator Container Image Check
    eff_img = get_effective_image_name()
    image_ready = check_image_exists(eff_img)
    if image_ready:
        print(f"  [✓] Operator Image: {eff_img} (built & ready)")
    else:
        print(f"  [-] Operator Image: '{IMAGE_NAME}' not built yet (run 'bin/operate build')")

    # 6. Antigravity AI Agent Authentication Check
    has_auth, auth_type = check_auth_available()
    if has_auth:
        print(f"  [✓] Gemini Authentication: {auth_type}")
    else:
        print("  [-] Gemini Authentication: not configured yet")
        print("      Run 'bin/operate login' or export GEMINI_API_KEY='your-key'")

    if all_ok:
        print("\nAll core host checks passed! You are ready to run `operate`.")
        return 0
    else:
        print("\nSome host requirements are missing. Review the errors above.")
        return 1


def cmd_login(args: argparse.Namespace) -> int:
    """Interactively authenticate with Google Antigravity inside the operator container."""
    eff_image = get_effective_image_name()
    host_gemini = Path.home() / ".gemini"
    host_gemini.mkdir(parents=True, exist_ok=True)

    docker_bin = shutil.which("docker") or "docker"
    if not check_image_exists(eff_image):
        print(f"==> Image '{eff_image}' not found locally. Attempting to pull...")
        res = subprocess.run([docker_bin, "pull", eff_image])
        if res.returncode != 0:
            print("[-] Pull failed. Please build the image with 'bin/operate build'.", file=sys.stderr)
            return 1

    print("==> Launching interactive Antigravity authentication...")
    print("    Follow the on-screen instructions to sign in with your Google account.")
    print(f"    Credentials will be saved to: {host_gemini / 'antigravity-cli'}\n")

    cmd = [
        docker_bin, "run", "-it", "--rm",
        "--name", "agy-operator-login",
        "-v", f"{host_gemini.resolve()}:/home/agent/.gemini",
        eff_image,
        "agy",
    ]
    return subprocess.run(cmd).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="operate",
        description="Headless AI agent runner for automated media hardlinks, Muxpress remuxing, and hardware AV1/HEVC compression.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: list
    p_list = subparsers.add_parser("list", help="List available processing recipes.")
    p_list.set_defaults(func=cmd_list)

    # Subcommand: run
    p_run = subparsers.add_parser("run", help="Run a recipe on media storage.")
    p_run.add_argument("recipe", help="Name of recipe (e.g., media-pipeline).")
    p_run.add_argument("source", help="Source folder in Downloads or Media (e.g. /storage/Downloads/Series).")
    p_run.add_argument("destination", nargs="?", default=None, help="Optional destination folder (e.g. /storage/Media/TV).")
    p_run.add_argument("-d", "--dest", default=None, help="Destination folder (alternative flag).")
    p_run.add_argument(
        "--mode",
        choices=["link", "remux", "compress", "full"],
        default="link",
        help="Operation mode: 'link' (hardlinks), 'remux' (merge to single MKV without transcode), 'compress' (re-encode), 'full' (remux + compress).",
    )
    p_run.add_argument(
        "--codec",
        choices=["auto", "av1", "hevc", "h264"],
        default="auto",
        help="Video codec: 'auto' (av1 for RDNA3/Ada, hevc for older), 'av1', 'hevc', 'h264'.",
    )
    p_run.add_argument(
        "--backend",
        choices=["auto", "vaapi", "nvenc", "software"],
        default="auto",
        help="Encoder backend: 'auto' (autodetect AMD/Intel VA-API or NVIDIA NVENC), 'vaapi', 'nvenc', 'software'.",
    )
    p_run.add_argument(
        "--device",
        default=None,
        help="Custom DRI render node path for VA-API (e.g. /dev/dri/renderD128).",
    )
    p_run.add_argument(
        "--remux",
        action="store_true",
        help="Merge external audio/subtitles/fonts into single MKV containers instead of separate hardlinks.",
    )
    p_run.add_argument(
        "--compress",
        action="store_true",
        help="Enable GPU hardware compression (AV1 / HEVC).",
    )
    p_run.add_argument(
        "--force", "--force-reencode", "--force-hevc",
        dest="force_reencode",
        action="store_true",
        help="Force re-encoding even if video stream is already in target codec (useful for heavy BDRips with high bitrates).",
    )
    p_run.add_argument(
        "--max-bitrate",
        type=int,
        default=None,
        help="Re-encode if video bitrate exceeds this threshold in kbps (e.g. 4500).",
    )
    p_run.add_argument(
        "--offline", "--no-network",
        dest="offline",
        action="store_true",
        help="Disable network access entirely (runs container with --network=none and uses offline regex for metadata).",
    )
    p_run.add_argument(
        "--no-proxy",
        dest="no_proxy",
        action="store_true",
        help="Bypass the local allowlist proxy and allow direct unconstrained network access.",
    )
    p_run.add_argument(
        "-q", "--quality", "--qp",
        dest="quality",
        type=int,
        default=28,
        help="Video compression quality: global_quality for VA-API, QP for NVENC, CRF for CPU (default: 28).",
    )
    p_run.add_argument(
        "--preset",
        default="p6",
        help="Encoder quality preset (default: p6).",
    )
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate actions, resolve titles, and output plan without modifying files.",
    )
    p_run.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Launch agent with full interactive TUI mode (useful for debugging).",
    )
    p_run.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable real-time action streaming and print only final turn response.",
    )
    p_run.add_argument(
        "--auto",
        action="store_true",
        help="Run without interactive confirmation prompts (unattended mode).",
    )
    p_run.add_argument(
        "--api-key",
        dest="api_key",
        default=None,
        help="Gemini API key for non-interactive headless authentication (or set GEMINI_API_KEY env var).",
    )
    p_run.set_defaults(func=cmd_run)

    # Subcommand: login
    p_login = subparsers.add_parser("login", help="Authenticate with Google Antigravity via interactive browser login.")
    p_login.set_defaults(func=cmd_login)

    # Subcommand: build
    p_build = subparsers.add_parser("build", help="Build the operator Docker container image.")
    p_build.add_argument(
        "--base-image",
        default="ghcr.io/retr0xcc/antigravity-sbx-patched:latest",
        help="Base image (default: ghcr.io/retr0xcc/antigravity-sbx-patched:latest).",
    )
    p_build.set_defaults(func=cmd_build)

    # Subcommand: doctor
    p_doc = subparsers.add_parser("doctor", help="Check host dependencies and readiness.")
    p_doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)
