**English** | [Русский](README.ru.md)

# Antigravity Operator

> Autonomous Headless AI Agent Runner: intelligent media library organization (Plex / Jellyfin), stream remuxing, and hardware **AV1** (AMD RDNA 3 / RX 7700 XT) & **HEVC** (AMD VA-API / NVIDIA NVENC) compression backed by Docker Sandboxes (SBX) and Docker Engine isolation.

[![CLI: operate](https://img.shields.io/badge/CLI-operate-blue.svg)](bin/operate)
[![Base: antigravity-sbx-patched](https://img.shields.io/badge/Base-antigravity--sbx--patched-blueviolet.svg)](https://github.com/Retr0xCC/antigravity-sbx-patched)
[![Docker: Sandboxes & Engine](https://img.shields.io/badge/Runtime-SBX%20%7C%20Docker-2496ED?logo=docker&logoColor=white)](docker/Dockerfile)
[![GPU: AMD AV1 & NVIDIA NVENC](https://img.shields.io/badge/GPU-AMD%20AV1%20%7C%20NVENC-ED1C24?logo=amd&logoColor=white)](#hardware-gpu-acceleration)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Codeberg](https://img.shields.io/badge/Codeberg-Main_Repo-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/Retr0xCC/antigravity-operator)
[![GitHub](https://img.shields.io/badge/GitHub-Mirror-181717?logo=github&logoColor=white)](https://github.com/Retr0xCC/antigravity-operator)

---

## Overview

Automated batch media processing (hundreds of gigabytes of video, companion audio streams, subtitles, and fonts) requires the AI agent to have direct privileges for running system tools (`ffmpeg`, `ffprobe`, `mkvmerge`) and managing the filesystem.

Running such an unconstrained agent directly on the host poses critical risks of uncontrolled host resource exhaustion (memory leaks, runaway ffmpeg forks, CPU starvation) and exposure of sensitive host resources (user home directory, SSH keys, credentials).

**Antigravity Operator** addresses this by isolating the autonomous Antigravity coding agent (`agy --dangerously-skip-permissions`) within a tightly constrained sandbox:

* **Host Protection & Resource Boundaries:** The host operating system, system filesystems, user home directory (`~/.ssh`, `~/.docker`), and Docker socket remain strictly invisible to the agent. Resource boundaries are enforced via CPU/memory quotas, PID limits, and Tini PID 1 zombie reaping.
* **The Shared Storage Trade-Off (Necessary Risk):** To enable Zero-Copy hardlinks (`os.link()`) without triggering the kernel `EXDEV` error, source downloads (`Downloads`) and the media library (`Media`) must reside on the same filesystem partition and be mounted together under a common read-write storage root (`/storage:rw`). This is a deliberate, necessary technical trade-off: container isolation protects the host system, while integrity within the storage partition relies on procedural agent discipline and atomic tooling.
* **Data Integrity & Atomic Safeguards:**
  - **Zero-Copy Hardlinks:** Original downloaded files in `Downloads` are never moved, renamed, or modified, keeping torrent seeding completely intact.
  - **Muxpress Rollback Guard:** Re-encoded streams (`.temp.mkv`) replace originals atomically (`os.replace`) and only if the compressed file is strictly smaller. In case of abort or size inflation, temporary files are destroyed and originals remain untouched.
  - **RAM-Disk Scratchpad (`/tmp`):** The agent working directory is backed by a 4 GB RAM `tmpfs`. The agent cannot clutter `/storage` with intermediate Python or shell scripts.
* **Runner Immutability (Strict Read-Only):** Operator source code, helper utilities, and recipes (`recipes/`) are mounted strictly in `:ro` mode. The agent cannot modify its runner logic or SOP instructions (`INSTRUCTIONS.md`).
* **Downstream from `antigravity-sbx-patched`:** Built directly on `ghcr.io/retr0xcc/antigravity-sbx-patched:latest` with pre-applied QNIX eligibility patch, locked `/home/agent/.local/bin/agy` binary permissions, and disabled auto-updates.
* **Docker Sandboxes (`sbx`) One-Shot Support:** Automated headless execution via `sbx run --rm` and `sbxenv-media.yaml` templates for non-GPU tasks.
* **AMD Radeon Hardware Acceleration (AV1 & HEVC):** Native support for AMD RDNA 3 graphics cards (including **Radeon RX 7700 XT**) via Mesa VA-API (`av1_vaapi`, `hevc_vaapi`), delivering 20–30% better compression in **AV1** over HEVC.
* **Support for NVIDIA NVENC & Intel QuickSync / VA-API:** Automatic host GPU detection (`amd`, `nvidia`, `intel`, or CPU software fallback).
* **Integrated Muxpress Engine:** Proven pipeline for episode matching, companion audio track mapping (`.mka`), subtitle styling (`.ass`), and font attachment (`-attach`) into unified monolithic `.mkv` containers for Jellyfin/Plex.
* **Canonical Metadata Enrichment:** Automatic semantic recognition of canonical titles and release years for movies, series, anime, and audiobooks (TMDb, IMDb, TheTVDB, Wikipedia, OpenLibrary).

---

## Architecture and Isolation

> [!IMPORTANT]
> **Runtime Selection Logic (`--runtime auto`):**
> * **For GPU compression tasks (`--compress`, `media-compress`, `media-pipeline`):**
>   Automatically dispatches to **Docker Engine** (`--runtime docker`). Standard Docker passes host hardware devices (`--device=/dev/dri:/dev/dri` with `video`/`render` groups for AMD/Intel or `--gpus all` for NVIDIA) directly into the container without microVM virtualization overhead.
> * **For Non-GPU tasks (`media-link`, `media-remux` without transcode):**
>   Automatically dispatches to **Docker Sandboxes (`sbx`)** (`--runtime sbx` if the `sbx` CLI is installed on the host). This provides complete microVM boundary isolation, strict network allowlists, proxy-managed `GEMINI_API_KEY` credential injection, and Zero-Copy hardlinks.
> * You can explicitly override the runtime at any time using `--runtime docker` or `--runtime sbx`.

```text
 ┌─────────────────────────────────────────────────────────────┐
 │                           Host                              │
 │                                                             │
 │   Protected Host Resources (Inaccessible to container):     │
 │   - Home directory (~/.ssh, ~/.gnupg, ~/.aws, ~/.docker)    │
 │   - Root filesystem (/) and system directories              │
 │   - Docker Daemon Socket (/var/run/docker.sock)             │
 │                                                             │
 │   Physical Storage Partition (ext4):                        │
 │   /home/retro/HDD-EXT4/ (Unified root for Downloads/Media)  │
 │                                                             │
 │   Hardware Accelerators:                                    │
 │   - AMD Radeon (RX 7700 XT): /dev/dri/renderD128 (VA-API)   │
 │   - or NVIDIA GeForce/RTX: --gpus all (CUDA NVENC)          │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
    [Runtime: Docker Engine]          [Runtime: Docker Sandboxes]
    --device=/dev/dri:/dev/dri        sbx run --rm ./kits/media-operator
    (Direct GPU Passthrough)          (Strict microVM Isolation)
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                Antigravity Operator Sandbox                 │
 │               (Base: antigravity-sbx-patched)               │
 │                                                             │
 │   - Unprivileged user: 'agent' (UID 1000)                   │
 │   - Kernel security: --security-opt=no-new-privileges:true  │
 │   - Fast RAM disk: --tmpfs=/tmp:rw,nosuid,nodev,size=4g     │
 │   - Resource limits: memory=8g, cpus=4, pids-limit=4096     │
 │   - Zombie process reaper: --init (Tini PID 1)              │
 │   - Media tools: ffmpeg (VAAPI/NVENC), mkvmerge, vainfo     │
 │   - Autonomous agent: agy (QNIX patched, immutable)         │
 │   - Persistent auth: agy-operator-config ──► ~/.gemini      │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                                 │  os.link(src, dst) inside /storage
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                         Filesystem                          │
 │                                                             │
 │   /storage/Downloads/ ──[Hardlink (same inode)]──► /storage/│
 │   (Torrents continue seeding)                        Media/ │
 │                                                             │
 │   During AV1/HEVC compression:                              │
 │   - Re-encoded file replaces only the copy in Media/        │
 │   - Original inode in Downloads/ remains intact for seeding!│
 └─────────────────────────────────────────────────────────────┘
```

---

## Host System Requirements

* **Operating System:** Linux (kernel 5.x/6.x) with ext4, btrfs, or zfs support.
* **Container Engine:** Docker Engine 20.10+ with Docker CLI and/or Docker Sandboxes (`sbx`).
* **Hardware GPU Acceleration:**
  * **AMD Radeon:** RX 7000 Series (RDNA 3 / Navi 3x, e.g. Radeon RX 7700 XT) with hardware **AV1** (`av1_vaapi`) and **HEVC** (`hevc_vaapi`) via the Mesa VA-API driver (`radeonsi`) on `/dev/dri/renderD128`.
  * **NVIDIA:** GeForce GTX 10xx, RTX 20xx/30xx/40xx with NVIDIA driver and **NVIDIA Container Toolkit**.
  * **Intel:** Arc / Iris Xe with QuickSync / VA-API support.
* **Python:** Python 3.10+ on the host for running the `bin/operate` CLI dispatcher.

> [!NOTE]
> Project development and profiling were conducted on an **AMD Radeon RX 7700 XT** (Linux, Mesa VA-API). Support for NVIDIA and Intel architectures is implemented and verified by command generation test suites, but has not been tested on physical NVIDIA/Intel hardware due to author availability.

---

## Quick Start

### 1. Host Environment Check

Audit your environment before running workflows:

```bash
bin/operate doctor
```

This verifies:
* Availability of Docker Engine and Docker Sandboxes CLI (`sbx`).
* Hardware GPU detection (AMD Radeon VA-API, NVIDIA CUDA NVENC, Intel).
* Hardware **AV1** encoder availability on AMD RDNA 3 / Ada Lovelace GPUs.
* System multimedia utilities (`vainfo`, `ffmpeg`) and recipe catalog integrity.

### 2. Build the Docker Image

The image builds downstream from `antigravity-sbx-patched`:

```bash
bin/operate build
```

*(Optionally override the base image via `--base-image <tag>`)*.

### 3. List Available Recipes

```bash
bin/operate list
```

---

## Use Cases and Scenarios

| Recipe | Purpose | Resources | Typical Runtime |
| :--- | :--- | :--- | :--- |
| **`media-link`** | Fast library organization via Zero-Copy hardlinks (IMDb + Plex/Jellyfin naming) | 0% GPU, 0% CPU | ~5–10 sec |
| **`media-remux`** | Lossless stream copy: mux companion audio, subtitles, and fonts into MKV (`-c copy`) | No re-encoding | ~20–40 sec |
| **`media-compress`**| Hardware AV1 / HEVC 10-bit compression with atomic rollback protection | GPU (AMD VA-API / NVENC) | GPU dependent |
| **`media-pipeline`**| Multi-stage end-to-end pipeline (Link + Remux + Compress) | Configurable | Comprehensive |

---

### Scenario 1. Zero-Copy Ingest (`media-link`)

Instant cataloging from `Downloads` to `Media` with online metadata matching while preserving continuous torrent seeding:

```bash
bin/operate run media-link /home/retro/HDD-EXT4/Downloads/The.Matrix.1999 /home/retro/HDD-EXT4/Media/Movies --imdb
```

### Scenario 2. Monolithic Container Remuxing (`media-remux`)

Merges external companion audio (`.mka`), subtitles (`.ass`), and styled fonts into a single container for Jellyfin without re-encoding:

```bash
bin/operate run media-remux /home/retro/HDD-EXT4/Downloads/Attack.on.Titan /home/retro/HDD-EXT4/Media/TV
```

### Scenario 3. Hardware AV1 Compression on AMD Radeon RX 7700 XT (`media-compress`)

On AMD RDNA 3 graphics cards, the operator automatically selects hardware **AV1** (`av1_vaapi`):

```bash
bin/operate run media-compress /home/retro/HDD-EXT4/Media/TV/Frieren --codec av1 --quality 28
```

* **Rollback Safety:** If the compressed file ends up larger than the original, the temporary file is deleted and the original is preserved.
* **Force Mode (`--force`):** Re-encodes videos even if they are already in the target codec, useful for heavy BDRip releases with excessive bitrates.

### Scenario 4. Docker Sandboxes (`sbx`) One-Shot Execution

Execute within a Docker Sandboxes microVM:

```bash
bin/operate run media-link /home/retro/HDD-EXT4/Downloads/Series /home/retro/HDD-EXT4/Media/TV --runtime sbx
```

Or call `sbx run` directly:

```bash
sbx run --rm ./kits/media-operator /home/retro/HDD-EXT4 -- \
  --dangerously-skip-permissions \
  --effort low \
  --output-format stream-json \
  -p "Organize media inside /storage/Media following media-link instructions"
```

---

## CLI Parameter Reference (`bin/operate`)

```text
operate run <recipe> <source> [destination] [options]
```

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `recipe` | — | Recipe name (`media-pipeline`, `media-link`, `media-remux`, `media-compress`) |
| `source` | — | Source path in `Downloads` or `Media` |
| `destination` / `-d` | Auto-detect | Destination media path (`TV`, `Movies`, `Books`) |
| `--runtime` | `auto` | Isolation runtime: `auto` (smart selection), `docker` (direct GPU), `sbx` (microVM) |
| `--codec` | `auto` | Target video codec: `auto` (AV1 for RDNA 3/Ada, HEVC for older), `av1`, `hevc`, `h264` |
| `--backend` | `auto` | Encoder backend: `auto` (AMD/Intel `vaapi`, NVIDIA `nvenc`, CPU `software`) |
| `--device` | Auto-detect | Path to DRI render node (e.g. `/dev/dri/renderD128`) |
| `-q`, `--quality`, `--qp` | `28` | Quality factor (CQP global_quality for VA-API, QP for NVENC, CRF for CPU) |
| `--preset` | `p6` | Quality/speed preset |
| `--mode` | `link` | Operational mode: `link`, `remux`, `compress`, `full` |
| `--remux` | `false` | Mux companion tracks/subs/fonts into monolithic `.mkv` files |
| `--compress` | `false` | Enable hardware GPU compression |
| `--force`, `--force-reencode` | `false` | Re-encode even if video stream is already in target codec |
| `--max-bitrate` | — | Bitrate threshold in kbps (e.g. `4500`): compress files exceeding this threshold |
| `--imdb`, `--metadata`| `false` | Query online metadata (TMDb, IMDb, Wikipedia, Cyclopedia) |
| `--dry-run` | `false` | Dry-run simulation: print planned actions without modifying filesystem |
| `--auto` | `false` | Unattended execution without interactive confirmation prompts |

---

## License and Disclaimer

* This project is licensed under the **[MIT License](LICENSE)** (© 2026 Retr0xCC).
* **Disclaimer**: This is an independent community project. It is not affiliated with, endorsed by, or sponsored by Google LLC or Docker, Inc. "Google Antigravity" is a trademark of Google LLC. "Docker" and "Docker Sandboxes" are trademarks of Docker, Inc.
