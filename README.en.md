**English** | [Русский](README.ru.md)

# Antigravity Operator

> Autonomous Headless AI Agent Runner: intelligent media library organization (Plex / Jellyfin), stream remuxing, and hardware **AV1** (AMD RDNA 3 / RX 7700 XT) & **HEVC** (AMD VA-API / NVIDIA NVENC) compression in an isolated Docker container.

[![CLI: operate](https://img.shields.io/badge/CLI-operate-blue.svg)](bin/operate)
[![Base: antigravity-sbx-patched](https://img.shields.io/badge/Base-antigravity--sbx--patched-blueviolet.svg)](https://github.com/Retr0xCC/antigravity-sbx-patched)
[![Docker: Engine](https://img.shields.io/badge/Runtime-Docker-2496ED?logo=docker&logoColor=white)](docker/Dockerfile)
[![GPU: AMD AV1 & NVIDIA NVENC](https://img.shields.io/badge/GPU-AMD%20AV1%20%7C%20NVENC-ED1C24?logo=amd&logoColor=white)](#hardware-gpu-acceleration)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Codeberg](https://img.shields.io/badge/Codeberg-Main_Repo-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/Retr0xCC/antigravity-operator)
[![GitHub](https://img.shields.io/badge/GitHub-Mirror-181717?logo=github&logoColor=white)](https://github.com/Retr0xCC/antigravity-operator)

---

## Overview

Automated batch media processing (hundreds of gigabytes of video, companion audio streams, subtitles, and fonts) requires the AI agent to have direct privileges for running system tools (`ffmpeg`, `ffprobe`, `mkvmerge`) and managing the filesystem.

Running such an unconstrained agent directly on the host poses critical risks of uncontrolled host resource exhaustion (memory leaks, runaway ffmpeg forks, CPU starvation) and exposure of sensitive host resources (user home directory, SSH keys, credentials).

**Antigravity Operator** addresses this by isolating the autonomous Antigravity coding agent (`agy --dangerously-skip-permissions`) within a tightly constrained Docker container:

* **Host Protection & Resource Boundaries:** The host operating system, system filesystems, user home directory (`~/.ssh`, `~/.docker`), and Docker socket remain strictly invisible to the agent. Resource boundaries are enforced via CPU/memory quotas, PID limits, and Tini PID 1 zombie reaping.
* **The Shared Storage Trade-Off (Necessary Risk):** To enable Zero-Copy hardlinks (`os.link()`) without triggering the kernel `EXDEV` error, source downloads (`Downloads`) and the media library (`Media`) must reside on the same filesystem partition and be mounted together under a common read-write storage root (`/storage:rw`). This is a deliberate, necessary technical trade-off: container isolation protects the host system, while integrity within the storage partition relies on procedural agent discipline and atomic tooling.
* **Data Integrity & Atomic Safeguards:**
  - **Zero-Copy Hardlinks:** Original downloaded files in `Downloads` are never moved, renamed, or modified, keeping torrent seeding completely intact.
  - **Muxpress Rollback Guard:** Re-encoded streams (`.temp.mkv`) replace originals atomically (`os.replace`) and only if the compressed file is strictly smaller. In case of abort or size inflation, temporary files are destroyed and originals remain untouched.
  - **RAM-Disk Scratchpad (`/tmp`):** The agent working directory is backed by a 4 GB RAM `tmpfs`. The agent cannot clutter `/storage` with intermediate Python or shell scripts.
* **Runner Immutability (Strict Read-Only):** Operator source code, helper utilities, and recipes (`recipes/`) are mounted strictly in `:ro` mode. The agent cannot modify its runner logic or SOP instructions (`INSTRUCTIONS.md`).
* **Downstream from `antigravity-sbx-patched`:** Built directly on `ghcr.io/retr0xcc/antigravity-sbx-patched:latest` with pre-applied QNIX eligibility patch, locked `/home/agent/.local/bin/agy` binary permissions, and disabled auto-updates.
* **AMD Radeon Hardware Acceleration (AV1 & HEVC):** Native support for AMD RDNA 3 graphics cards (including **Radeon RX 7700 XT**) via Mesa VA-API (`av1_vaapi`, `hevc_vaapi`), delivering 20–30% better compression in **AV1** over HEVC.
* **Support for NVIDIA NVENC & Intel QuickSync / VA-API:** Automatic host GPU detection (`amd`, `nvidia`, `intel`, or CPU software fallback).
* **Integrated Muxpress Engine:** Proven pipeline for episode matching, companion audio track mapping (`.mka`), subtitle styling (`.ass`), and font attachment (`-attach`) into unified monolithic `.mkv` containers for Jellyfin/Plex.
* **Canonical Metadata Enrichment by Default:** Automatic semantic recognition of canonical titles and release years for movies, series, anime, and audiobooks (TMDb, IMDb, TheTVDB, Wikipedia, OpenLibrary).
* **Built-in Ephemeral Egress Proxy (Allowlist + LAN/SSRF Protection):** Automatically starts an in-memory forward proxy on a dynamic host port. Whitelists only Google Gemini API and metadata providers (IMDb/TMDb/Wikipedia). All requests to the local home network (RFC 1918: 192.168.x.x, 10.x.x.x, 127.x.x.x) and untrusted internet destinations are rejected (403 Forbidden). Requires zero root/iptables rights and leaves no system traces.
* **Network Isolation and Airgapped Mode (`--offline`):** Complete network shutdown via `--network=none` for deterministic runs.

---

## Architecture and Isolation

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
 │   /home/retro/HDD-EXT4/ (shared root of Downloads & Media)  │
 │                                                             │
 │   Hardware Accelerators:                                    │
 │   - AMD Radeon (RX 7700 XT): /dev/dri/renderD128 (VA-API)   │
 │   - or NVIDIA GeForce/RTX: --gpus all (CUDA NVENC)         │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
                     [Docker Engine Container]
                     --device=/dev/dri:/dev/dri
 ┌─────────────────────────────────────────────────────────────┐
 │               Antigravity Operator Sandbox                  │
 │               (Base: antigravity-sbx-patched)               │
 │                                                             │
 │   - Non-privileged user: 'agent' (UID 1000)                 │
 │   - Kernel security: --security-opt=no-new-privileges:true  │
 │   - Drop raw network capabilities: --cap-drop=NET_RAW       │
 │   - Networking: bridge with Dual-DNS (or none in --offline) │
 │   - Fast RAM scratchpad: --tmpfs=/tmp:rw,nosuid,nodev       │
 │   - Resource limits: memory=8g, cpus=4, pids-limit=4096     │
 │   - Zombie process reaper: --init (Tini PID 1)              │
 │   - Media tools: ffmpeg (VAAPI/NVENC), mkvmerge, vainfo     │
 │   - Autonomous agent: agy (QNIX patched, immutable)         │
 │   - Sessions: agy-operator-config ──► /home/agent/.gemini   │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                                 │  os.link(src, dst) inside /storage
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                         Filesystem                          │
 │                                                             │
 │   /storage/Downloads/ ──[Hardlink (same inode)]──► /storage/│
 │   (Torrents seeding)                                 Media/ │
 │                                                             │
 │   Under AV1/HEVC compression:                               │
 │   - Compressed file replaces only destination in Media/     │
 │   - Original inode in Downloads/ continues seeding!         │
 └─────────────────────────────────────────────────────────────┘
```

---

## Host Requirements

* **Operating System:** Linux (kernel 5.x/6.x) with ext4, btrfs, or zfs support.
* **Container Engine:** Docker Engine 20.10+ with Docker CLI.
* **Hardware Acceleration (GPU):**
  * **AMD Radeon:** RX 7000 Series (RDNA 3 / Navi 3x, e.g. Radeon RX 7700 XT) with hardware **AV1** (`av1_vaapi`) and **HEVC** (`hevc_vaapi`) via Mesa VA-API (`radeonsi`) on `/dev/dri/renderD128`.
  * **NVIDIA:** GeForce GTX 10xx, RTX 20xx/30xx/40xx with NVIDIA driver and **NVIDIA Container Toolkit**.
  * **Intel:** Arc / Iris Xe with QuickSync / VA-API.
* **Python:** Python 3.10+ on host for `bin/operate` CLI dispatcher.

> [!NOTE]
> Testing and profiling were performed on an **AMD Radeon RX 7700 XT** (Linux, Mesa VA-API). NVIDIA and Intel support is designed into the architecture and validated via test suites, but has not been tested on physical NVIDIA/Intel hardware due to unavailability of these devices.

---

## Quick Start

### 1. Environment Audit

Check host readiness before starting:

```bash
bin/operate doctor
```

The command verifies:
* Docker Engine presence.
* Hardware GPU accelerators (AMD Radeon VA-API, NVIDIA CUDA NVENC, Intel).
* **AV1** hardware encoder capabilities.
* VA-API tools (`vainfo`), FFmpeg, and recipes catalog.
* Local status of `antigravity-operator:latest` image.

### 2. Build Container Image

Builds downstream from `ghcr.io/retr0xcc/antigravity-sbx-patched:latest`:

```bash
bin/operate build
```

*(Optionally override the base image with `--base-image <tag>`)*.

### 3. List Available Recipes

```bash
bin/operate list
```

---

## Usage Scenarios

| Recipe | Purpose | Resource Footprint | Runtime |
| :--- | :--- | :--- | :--- |
| **`media-link`** | Fast library organization via Zero-Copy hardlinks (IMDb + Plex/Jellyfin naming) | 0% GPU, 0% CPU | ~5–10s |
| **`media-remux`** | Lossless audio/subtitle/font muxing into monolithic MKV (`-c copy`) | No re-encoding | ~20–40s |
| **`media-compress`**| Hardware AV1 / HEVC 10-bit compression with Rollback Guard | GPU (AMD VA-API / NVENC) | Proportional |
| **`media-pipeline`**| Multi-stage complete workflow (Link + Remux + Compress) | Configurable | Complex |

---

### Scenario 1. Fast Transfer from `Downloads` to `Media` (`media-link`)

Instant addition to media library with canonical title matching and Zero-Copy torrent preservation:

```bash
bin/operate run media-link /home/retro/HDD-EXT4/Downloads/The.Matrix.1999 /home/retro/HDD-EXT4/Media/Movies
```

*(Metadata resolution via IMDb / Wikipedia is enabled by default)*.

### Scenario 2. Audio Track and Font Remuxing (`media-remux`)

Combines video, external audio tracks (`.mka`), subtitles (`.ass`), and embedded fonts into a single file for Jellyfin without re-encoding video:

```bash
bin/operate run media-remux /home/retro/HDD-EXT4/Downloads/Attack.on.Titan /home/retro/HDD-EXT4/Media/TV
```

### Scenario 3. Hardware AV1 Compression on AMD Radeon RX 7700 XT (`media-compress`)

On AMD RDNA 3 GPUs, the operator automatically selects the **AV1** hardware codec (`av1_vaapi`):

```bash
bin/operate run media-compress /home/retro/HDD-EXT4/Media/TV/Frieren --codec av1 --quality 28
```

* **Rollback Guard:** If the re-encoded file is larger than the original, the temporary file is deleted and the original remains unchanged.
* **Forced Compression (`--force`):** Re-encodes files that are already in the target codec if their bitrate is excessive (e.g. heavy BDRips).

### Scenario 4. Completely Isolated Airgapped Execution (`--offline`)

Run the container completely offline with `--network=none`:

```bash
bin/operate run media-link /home/retro/HDD-EXT4/Downloads/Series /home/retro/HDD-EXT4/Media/TV --offline
```

* Container runs with `--network=none` (zero inbound/outbound network access).
* Title canonicalization uses offline local token and regex parsing.

---

## CLI Reference `bin/operate`

```text
operate run <recipe> <source> [destination] [options]
```

| Option | Default | Description |
| :--- | :--- | :--- |
| `recipe` | — | Recipe name (`media-pipeline`, `media-link`, `media-remux`, `media-compress`) |
| `source` | — | Source folder in `Downloads` or `Media` |
| `destination` / `-d` | Auto-detect | Target library category folder (`TV`, `Movies`, `Books`) |
| `--mode` | `link` | Operating mode: `link`, `remux`, `compress`, `full` |
| `--codec` | `auto` | Target video codec: `auto` (AV1 for RDNA 3/Ada, HEVC for older), `av1`, `hevc`, `h264` |
| `--backend` | `auto` | Encoder backend: `auto` (AMD/Intel `vaapi`, NVIDIA `nvenc`, CPU `software`) |
| `--device` | Auto-detect | Custom DRI render node (e.g. `/dev/dri/renderD128`) |
| `-q`, `--quality`, `--qp` | `28` | Compression quality (CQP global_quality for VA-API, QP for NVENC, CRF for CPU) |
| `--preset` | `p6` | Encoder speed/quality preset |
| `--remux` | `false` | Pack external audio/subtitles/fonts into unified `.mkv` |
| `--compress` | `false` | Enable GPU hardware compression |
| `--force`, `--force-reencode` | `false` | Force re-encoding even if stream is already in target codec |
| `--max-bitrate` | — | Bitrate threshold in kbps (e.g. `4500`): re-encode files exceeding this value |
| `--offline`, `--no-network` | `false` | Completely disable network (`--network=none`, offline regex parsing) |
| `--no-proxy` | `false` | Bypass the ephemeral allowlist proxy and allow direct unconstrained network access |
| `--dry-run` | `false` | Dry-run simulation: print plan without modifying filesystem |
| `--auto` | `false` | Unattended automated execution without prompts |

---

## License & Disclaimers

* Source code is distributed under the **[MIT License](LICENSE)** (© 2026 Retr0xCC).
* **Disclaimer**: This is an independent community project. It is not affiliated with, sponsored by, or endorsed by Google LLC or Docker, Inc. "Google Antigravity" is a trademark of Google LLC. "Docker" is a trademark of Docker, Inc.
