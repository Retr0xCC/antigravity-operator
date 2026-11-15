"""Security validation and path resolution for antigravity-operator.

Enforces strict path checks, filesystem boundaries, and common storage root resolution
to prevent EXDEV (cross-device link) errors when creating hardlinks across source and destination.
"""

from __future__ import annotations

import os
from pathlib import Path

# System directories that must NEVER be mounted as writable storage
SYSTEM_BLACKLIST = [
    "/",
    "/etc",
    "/usr",
    "/var",
    "/dev",
    "/run",
    "/proc",
    "/sys",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/root",
    "/var/run/docker.sock",
    "/run/docker.sock",
]

# Sensitive subdirectories within $HOME
SENSITIVE_HOME_DIRS = [
    ".ssh",
    ".gnupg",
    ".aws",
    ".docker",
    ".kube",
    ".config",
    ".local",
]


class SecurityError(Exception):
    """Raised when a path violates security boundaries."""
    pass


def validate_storage_path(raw_path: str | Path, allow_nonexistent: bool = False) -> Path:
    """Validate that the given path is safe and does not violate security blacklists."""
    p = Path(raw_path).expanduser().resolve()

    if not allow_nonexistent:
        if not p.exists():
            raise SecurityError(f"Target path does not exist: {p}")
        if not p.is_dir() and not p.is_file():
            raise SecurityError(f"Target path is neither a file nor a directory: {p}")

    canonical_str = str(p)

    # 1. Check system blacklist
    for sys_dir in SYSTEM_BLACKLIST:
        if canonical_str == sys_dir or canonical_str.startswith(f"{sys_dir}/"):
            if sys_dir == "/":
                if canonical_str == "/":
                    raise SecurityError("Host mount path '/' is strictly blacklisted for security.")
            else:
                raise SecurityError(f"Path '{p}' is inside protected system directory '{sys_dir}'.")

    # 2. Check full user HOME directory directly
    home = Path.home().resolve()
    if p == home:
        raise SecurityError(
            f"Mounting entire user HOME '{home}' is disallowed. Specify a dedicated storage directory."
        )

    # 3. Check sensitive home subdirectories
    for sens in SENSITIVE_HOME_DIRS:
        sens_path = home / sens
        if p == sens_path or str(p).startswith(f"{sens_path}/"):
            raise SecurityError(f"Path '{p}' contains sensitive directory '{sens}'. Disallowed.")

    return p


def resolve_storage_boundaries(
    source_path: str | Path,
    dest_path: str | Path | None = None,
) -> tuple[Path, str, str | None]:
    """Resolve storage root to guarantee the same filesystem for hardlinks (preventing EXDEV).

    Finds the common root containing source_path (and dest_path if provided),
    and computes the container relative subpaths under /storage.

    Returns:
        (common_storage_root, source_subpath, dest_subpath_or_none)
    """
    valid_src = validate_storage_path(source_path)
    valid_dest = validate_storage_path(dest_path, allow_nonexistent=True) if dest_path else None

    if valid_dest:
        # Find common ancestor between source and destination
        common = Path(os.path.commonpath([str(valid_src), str(valid_dest)]))
        # Validate that common root is safe
        validate_storage_path(common, allow_nonexistent=False)

        # Make sure common root is not just '/' or home root
        if common in (Path("/"), Path.home().resolve()):
            raise SecurityError(
                f"Source ({valid_src}) and Destination ({valid_dest}) do not share a safe storage root. "
                "Both must reside on the same filesystem/partition (e.g., /home/retro/HDD-EXT4)."
            )

        storage_root = common
        src_sub = str(valid_src.relative_to(storage_root))
        dest_sub = str(valid_dest.relative_to(storage_root))
        return storage_root, ("" if src_sub == "." else src_sub), ("" if dest_sub == "." else dest_sub)

    # Single path given: find parent containing 'Downloads' or 'Media'
    curr = valid_src
    storage_root = valid_src

    for parent in [curr] + list(curr.parents):
        if (parent / "Downloads").exists() or (parent / "Media").exists():
            storage_root = parent
            break
        if parent == Path.home().resolve() or parent == Path("/"):
            break

    try:
        rel_sub = valid_src.relative_to(storage_root)
        src_sub_str = "" if str(rel_sub) == "." else str(rel_sub)
    except ValueError:
        storage_root = valid_src
        src_sub_str = ""

    return storage_root, src_sub_str, None
