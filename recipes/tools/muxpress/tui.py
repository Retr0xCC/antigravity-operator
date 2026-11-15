"""Terminal User Interface (TUI) and interactive setup wizard for Muxpress.

Zero-dependencies: uses standard library (readline, termios, tty) and ANSI escape sequences.
All prompts and menus are in English.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

from .models import EncoderSettings, PipelineConfig

# Try to import readline for Tab auto-completion
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

# Try to import termios & tty for arrow-key navigation
try:
    import termios
    import tty
    TERMIOS_AVAILABLE = True
except ImportError:
    TERMIOS_AVAILABLE = False


def _path_completer(text: str, state: int) -> str | None:
    """Readline completer for filesystem paths with auto-completion on Tab."""
    text_expanded = os.path.expanduser(os.path.expandvars(text))
    dirname = os.path.dirname(text_expanded) or "."
    basename = os.path.basename(text_expanded)

    try:
        matches = []
        for entry in sorted(os.listdir(dirname)):
            if entry.startswith(basename):
                full = os.path.join(dirname, entry)
                if os.path.isdir(full):
                    entry += "/"
                prefix = os.path.dirname(text)
                res = os.path.join(prefix, entry) if prefix else entry
                matches.append(res)
        return matches[state] if state < len(matches) else None
    except OSError:
        return None


def setup_tab_completion() -> None:
    """Enable Tab auto-completion for filesystem paths."""
    if not READLINE_AVAILABLE:
        return
    try:
        readline.set_completer_delims(" \t\n;\"'")
        readline.set_completer(_path_completer)
        # MacOS libedit vs GNU readline
        if "libedit" in getattr(readline, "__doc__", ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")
    except Exception:
        pass


def _read_key() -> str:
    """Read a single keypress or escape sequence from stdin."""
    if not TERMIOS_AVAILABLE or not sys.stdin.isatty():
        return ""

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch1 = sys.stdin.read(1)
        if ch1 == "\x1b":  # ESC sequence
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "UP"
                elif ch3 == "B":
                    return "DOWN"
                elif ch3 == "C":
                    return "RIGHT"
                elif ch3 == "D":
                    return "LEFT"
            return "ESC"
        elif ch1 in ("\r", "\n"):
            return "ENTER"
        elif ch1 == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        return ch1
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def select_option(title: str, options: Sequence[str], default_index: int = 0) -> int:
    """Interactive arrow-key option selector.

    Falls back to numeric input if terminal raw mode is unavailable.
    """
    if not (TERMIOS_AVAILABLE and sys.stdin.isatty() and sys.stdout.isatty()):
        # Fallback to plain prompt
        print(f"\n{title}")
        for i, opt in enumerate(options, 1):
            marker = "*" if i - 1 == default_index else " "
            print(f"  {marker} {i}. {opt}")
        while True:
            try:
                choice = input(f"Select option [1-{len(options)}] (default {default_index + 1}): ").strip()
                if not choice:
                    return default_index
                val = int(choice)
                if 1 <= val <= len(options):
                    return val - 1
            except (ValueError, EOFError, KeyboardInterrupt):
                return default_index
            print(f"Please enter a number between 1 and {len(options)}.")

    current = default_index
    num_options = len(options)

    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        # Initial render
        print(f"\n{title} (Use ↑/↓ arrows and press Enter):")
        for i, opt in enumerate(options):
            if i == current:
                print(f"  \033[1;36m❯ {opt}\033[0m")
            else:
                print(f"    {opt}")

        while True:
            key = _read_key()
            if key == "UP":
                current = (current - 1) % num_options
            elif key == "DOWN":
                current = (current + 1) % num_options
            elif key == "ENTER":
                return current
            elif key == "ESC":
                return default_index

            # Move cursor back up and redraw
            sys.stdout.write(f"\033[{num_options}A")
            for i, opt in enumerate(options):
                # Clear line and print
                sys.stdout.write("\033[2K")
                if i == current:
                    print(f"  \033[1;36m❯ {opt}\033[0m")
                else:
                    print(f"    {opt}")
            sys.stdout.flush()

    finally:
        # Restore cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def prompt_path(prompt_text: str = "Path to directory or .mkv file [Tab for auto-complete]", default: str = ".") -> Path:
    """Prompt user for a filesystem path with Tab auto-completion."""
    setup_tab_completion()
    try:
        val = input(f"📂 {prompt_text} (default: '{default}'): ").strip()
        if not val:
            val = default
        # Strip surrounding quotes if dragged & dropped from GUI file manager
        val = val.strip("'\"")
        return Path(val).expanduser()
    except (EOFError, KeyboardInterrupt):
        return Path(default)


def prompt_text(prompt: str, default: str | None = None) -> str | None:
    """Prompt for string input."""
    def_str = f" (default: '{default}')" if default is not None else " [press Enter to auto-detect]"
    try:
        val = input(f"{prompt}{def_str}: ").strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        return default


def prompt_int(prompt: str, default: int = 0) -> int:
    """Prompt for integer input."""
    while True:
        try:
            val = input(f"{prompt} (default: {default}): ").strip()
            if not val:
                return default
            return int(val)
        except ValueError:
            print("Please enter a valid integer.")
        except (EOFError, KeyboardInterrupt):
            return default


def prompt_yes_no(prompt: str, default: bool = False) -> bool:
    """Prompt for yes/no confirmation."""
    def_hint = "[Y/n]" if default else "[y/N]"
    try:
        val = input(f"{prompt} {def_hint}: ").strip().lower()
        if not val:
            return default
        return val in ("y", "yes", "true", "1")
    except (EOFError, KeyboardInterrupt):
        return default


def run_interactive_wizard() -> PipelineConfig | None:
    """Run interactive configuration wizard in English.

    Returns configured PipelineConfig or None if user canceled.
    """
    print("\n" + "=" * 60)
    print("      🎬  Muxpress: Interactive Setup Wizard")
    print("=" * 60)

    # 1. Select Operation Mode
    mode_options = [
        "Full Pipeline   (Lossless Mux + NVENC HEVC Compression)",
        "Merge Only      (Lossless remux without video re-encoding)",
        "Compress Only   (Hardware NVENC HEVC compression for existing files)",
        "Dry Run         (Inspect tracks/fonts and print FFmpeg commands)",
    ]
    mode_idx = select_option("Select Operation Mode:", mode_options, default_index=0)

    merge_only = (mode_idx == 1)
    compress_only = (mode_idx == 2)
    dry_run = (mode_idx == 3)

    print()
    # 2. Target Path
    target_path = prompt_path(
        prompt_text="Enter path to series folder or single .mkv file",
        default=".",
    )

    custom_title = None
    custom_season = None
    episode_offset = 0
    output_dir = Path("merge-output")
    delete_sources = False

    # 3. Muxing Settings (if not compress-only)
    if not compress_only:
        print("\n--- Muxing Configuration ---")
        title_in = prompt_text("📝 Series/Movie title override", default=None)
        if title_in:
            custom_title = title_in

        season_in = prompt_text("🔢 Season number override", default=None)
        if season_in and season_in.isdigit():
            custom_season = int(season_in)

        episode_offset = prompt_int("🔢 Episode offset to subtract", default=0)
        out_dir_in = prompt_text("📁 Output directory", default="merge-output")
        output_dir = Path(out_dir_in) if out_dir_in else Path("merge-output")
        delete_sources = prompt_yes_no("🗑️  Delete source files after successful merge?", default=False)

    # 4. Encoder Settings (if not merge-only)
    preset = "p6"
    qp = 28
    gpu = 0
    force_hevc = False

    if not merge_only:
        print("\n--- NVENC Encoder Configuration ---")
        preset_options = [
            "p6 - High Quality (Recommended default)",
            "p7 - Maximum Quality (Slowest)",
            "p5 - Medium Quality",
            "p4 - Balanced Speed / Quality",
            "p3 - Fast",
            "p1 - Fastest (Lowest Quality)",
        ]
        preset_idx = select_option("Select NVENC Quality Preset:", preset_options, default_index=0)
        preset_map = ["p6", "p7", "p5", "p4", "p3", "p1"]
        preset = preset_map[preset_idx]

        qp = prompt_int("🎯 Constant QP parameter (lower = higher bitrate)", default=28)
        gpu = prompt_int("🎮 NVIDIA GPU Device Index", default=0)
        force_hevc = prompt_yes_no("⚡ Force re-encode even if video is already HEVC?", default=False)

    encoder_settings = EncoderSettings(
        preset=preset,
        qp=qp,
        gpu=gpu,
        force_hevc=force_hevc,
    )

    # 5. Review Summary
    print("\n" + "-" * 60)
    print("📋  Configuration Summary:")
    print(f"  • Target:         {target_path}")
    mode_str = "Full Pipeline"
    if merge_only:
        mode_str = "Merge Only"
    elif compress_only:
        mode_str = "Compress Only"
    elif dry_run:
        mode_str = "Dry Run"
    print(f"  • Mode:           {mode_str}")

    if not compress_only:
        print(f"  • Title Override: {custom_title or 'Auto-detect'}")
        print(f"  • Season:         {custom_season if custom_season is not None else 'Auto-detect'}")
        if episode_offset:
            print(f"  • Ep. Offset:     -{episode_offset}")
        print(f"  • Output Dir:     {output_dir}")
        print(f"  • Delete Sources: {'Yes' if delete_sources else 'No'}")

    if not merge_only:
        print(f"  • NVENC Preset:   {preset}")
        print(f"  • Const QP:       {qp}")
        print(f"  • GPU Device:     {gpu}")
        print(f"  • Force HEVC:     {'Yes' if force_hevc else 'No'}")
    print("-" * 60)

    confirm = prompt_yes_no("🚀 Start execution with these settings?", default=True)
    if not confirm:
        print("Aborted by user.")
        return None

    return PipelineConfig(
        target_path=target_path,
        output_dir=output_dir,
        custom_title=custom_title,
        custom_season=custom_season,
        episode_offset=episode_offset,
        merge_only=merge_only,
        compress_only=compress_only,
        dry_run=dry_run,
        delete_sources=delete_sources,
        encoder=encoder_settings,
    )
