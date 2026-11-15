"""Safe execution engine for Antigravity Media Operator plans (plan.json).

Executes media organization and transcoding plans natively on the host:
- Safe execution using shell=False to prevent command injection from torrent titles.
- Hardlinking with EXDEV cross-filesystem fallback.
- Native host GPU hardware transcoding (VA-API / NVENC / CPU).
- Atomic replacement and size rollback safety.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger("antigravity.plan")


class PlanError(Exception):
    """Raised when plan validation or execution fails."""


def load_plan(plan_path: Path | str) -> dict[str, Any]:
    """Read and parse plan.json."""
    p = Path(plan_path)
    if not p.is_file():
        raise PlanError(f"Plan file not found: {plan_path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise PlanError(f"Failed to parse plan JSON: {e}") from e


def validate_plan(data: dict[str, Any]) -> list[str]:
    """Validate plan structure. Returns a list of error strings (empty if valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Plan root must be a JSON object"]

    actions = data.get("actions")
    if not isinstance(actions, list):
        return ["Plan must contain an 'actions' list"]

    for i, act in enumerate(actions):
        if not isinstance(act, dict):
            errors.append(f"Action #{i} must be an object")
            continue
        act_type = act.get("type")
        if act_type not in ("mkdir", "link", "remux", "transcode"):
            errors.append(f"Action #{i} has unsupported type: {act_type}")
            continue

        if act_type == "mkdir":
            if not act.get("path"):
                errors.append(f"Action #{i} (mkdir) missing 'path'")
        elif act_type in ("link", "remux", "transcode"):
            if not act.get("src"):
                errors.append(f"Action #{i} ({act_type}) missing 'src'")
            if not act.get("dst"):
                errors.append(f"Action #{i} ({act_type}) missing 'dst'")

    return errors


def execute_action(
    action: dict[str, Any],
    dry_run: bool = False,
    progress_cb: Callable[[str], None] | None = None,
) -> bool:
    """Execute a single plan action safely on the host."""
    act_type = action["type"]
    msg = f"Executing {act_type}: "

    def report(text: str) -> None:
        if progress_cb:
            progress_cb(text)
        else:
            print(text)

    if act_type == "mkdir":
        target = Path(action["path"])
        report(f"[MKDIR] {target}")
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
        return True

    src = Path(action["src"])
    dst = Path(action["dst"])

    if not dry_run and not src.exists():
        report(f"[ERROR] Source file missing: {src}")
        return False

    # Ensure parent directory exists
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)

    if act_type == "link":
        report(f"[LINK] {src.name} -> {dst}")
        if dry_run:
            return True

        if dst.exists():
            try:
                if os.path.samefile(src, dst):
                    report(f"  [OK] Already linked: {dst.name}")
                    return True
            except OSError:
                pass
            dst.unlink()

        try:
            os.link(src, dst)
            return True
        except OSError as e:
            # Cross-device link fallback (different filesystems/partitions)
            if e.errno == 18:  # EXDEV
                report(f"  [WARN] Cross-device link not supported; copying instead: {dst.name}")
                shutil.copy2(src, dst)
                return True
            report(f"  [ERROR] Link failed: {e}")
            return False

    elif act_type == "remux":
        report(f"[REMUX] {src.name} -> {dst}")
        if dry_run:
            return True

        tmp_dst = dst.with_suffix(".tmp.mkv")
        if tmp_dst.exists():
            tmp_dst.unlink()

        # Build safe mkvmerge or ffmpeg command
        mkvmerge = shutil.which("mkvmerge")
        if mkvmerge:
            cmd = [mkvmerge, "-o", str(tmp_dst), str(src)]
            for audio in action.get("audio", []):
                if os.path.exists(audio):
                    cmd.append(str(audio))
            for sub in action.get("subtitles", []):
                if os.path.exists(sub):
                    cmd.append(str(sub))
        else:
            ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
            cmd = [ffmpeg, "-y", "-i", str(src), "-c", "copy", str(tmp_dst)]

        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
            if res.returncode != 0:
                report(f"  [ERROR] Remux failed: {res.stderr.decode('utf-8', errors='ignore')[:200]}")
                if tmp_dst.exists():
                    tmp_dst.unlink()
                return False
            os.replace(tmp_dst, dst)
            return True
        except Exception as e:
            report(f"  [ERROR] Remux execution error: {e}")
            if tmp_dst.exists():
                tmp_dst.unlink()
            return False

    elif act_type == "transcode":
        backend = action.get("backend", "vaapi")
        encoder = action.get("encoder", "av1_vaapi")
        device = action.get("device", "/dev/dri/renderD128")
        quality = action.get("quality", 28)
        report(f"[TRANSCODE] {src.name} ({encoder}, Q={quality}) -> {dst}")
        if dry_run:
            return True

        tmp_dst = dst.with_suffix(".transcoding.tmp.mkv")
        if tmp_dst.exists():
            tmp_dst.unlink()

        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        cmd: list[str] = [ffmpeg, "-y"]

        if backend == "vaapi":
            dev_str = device if (device and os.path.exists(device)) else "/dev/dri/renderD128"
            cmd.extend([
                "-hwaccel", "vaapi",
                "-vaapi_device", dev_str,
                "-hwaccel_output_format", "vaapi",
                "-i", str(src),
                "-vf", "format=nv12|vaapi,hwupload",
                "-c:v", encoder,
                "-qp", str(quality),
                "-c:a", "copy",
                "-c:s", "copy",
                str(tmp_dst),
            ])
        elif backend == "nvenc":
            cmd.extend([
                "-hwaccel", "cuda",
                "-i", str(src),
                "-c:v", encoder,
                "-cq", str(quality),
                "-c:a", "copy",
                "-c:s", "copy",
                str(tmp_dst),
            ])
        else:
            # Software fallback
            cmd.extend([
                "-i", str(src),
                "-c:v", encoder,
                "-crf", str(quality),
                "-c:a", "copy",
                "-c:s", "copy",
                str(tmp_dst),
            ])

        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
            if res.returncode != 0:
                report(f"  [ERROR] Transcode failed: {res.stderr.decode('utf-8', errors='ignore')[:200]}")
                if tmp_dst.exists():
                    tmp_dst.unlink()
                return False

            # Size Rollback Safety: check if compressed file is actually smaller
            orig_size = src.stat().st_size
            comp_size = tmp_dst.stat().st_size
            if comp_size >= orig_size and not action.get("force_keep", False):
                report(f"  [ROLLBACK] Transcoded size ({comp_size} B) >= Original ({orig_size} B). Keeping hardlink.")
                tmp_dst.unlink()
                if dst.exists():
                    dst.unlink()
                os.link(src, dst)
                return True

            os.replace(tmp_dst, dst)
            saved_mb = (orig_size - comp_size) / (1024 * 1024)
            report(f"  [SAVED] {saved_mb:.1f} MB saved! Committed: {dst.name}")
            return True
        except Exception as e:
            report(f"  [ERROR] Transcode error: {e}")
            if tmp_dst.exists():
                tmp_dst.unlink()
            return False

    return False


def execute_plan(
    plan_path: Path | str,
    dry_run: bool = False,
    progress_cb: Callable[[str], None] | None = None,
) -> bool:
    """Execute all actions in plan.json."""
    data = load_plan(plan_path)
    errs = validate_plan(data)
    if errs:
        raise PlanError(f"Invalid plan format:\n" + "\n".join(f"- {e}" for e in errs))

    actions = data.get("actions", [])
    total = len(actions)
    success_count = 0

    prefix = "[SIMULATION] " if dry_run else ""
    if progress_cb:
        progress_cb(f"==> {prefix}Executing plan with {total} action(s)...")
    else:
        print(f"==> {prefix}Executing plan with {total} action(s)...")

    for i, act in enumerate(actions, 1):
        if execute_action(act, dry_run=dry_run, progress_cb=progress_cb):
            success_count += 1

    summary = f"\n==> {prefix}Finished: {success_count}/{total} action(s) successful."
    if progress_cb:
        progress_cb(summary)
    else:
        print(summary)

    return success_count == total
