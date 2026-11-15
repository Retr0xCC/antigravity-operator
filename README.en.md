**English** | [Русский](README.ru.md)

# Antigravity Operator

> Autonomous agent for Plex/Jellyfin media organization ([TRaSH Guides](https://trash-guides.info/Hardlinks/Hardlinks-and-Instant-Moves/)), stream remuxing, and hardware AV1/HEVC compression in Docker.

[![CLI: operate](https://img.shields.io/badge/CLI-operate-blue.svg)](bin/operate)
[![Base: antigravity-sbx-patched](https://img.shields.io/badge/Base-antigravity--sbx--patched-blueviolet.svg)](https://github.com/Retr0xCC/antigravity-sbx-patched)
[![Runtime: Docker Engine](https://img.shields.io/badge/Runtime-Docker%20Engine-2496ED?logo=docker&logoColor=white)](docker/Dockerfile)
[![GPU: AMD AV1 & NVIDIA NVENC](https://img.shields.io/badge/GPU-AMD%20AV1%20%7C%20NVENC-ED1C24?logo=amd&logoColor=white)](#hardware-gpu-acceleration)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Codeberg](https://img.shields.io/badge/Codeberg-Main_Repo-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/Retr0xCC/antigravity-operator)
[![GitHub](https://img.shields.io/badge/GitHub-Mirror-181717?logo=github&logoColor=white)](https://github.com/Retr0xCC/antigravity-operator)

---

## Preface and Purpose

### The Home Media Server Dilemma
Every home theater administrator running **Plex**, **Jellyfin**, or **Emby** faces a fundamental conflict between two systems:
1. **Media servers require strict canonical naming:** for scrapers to reliably match posters, fanart, metadata, and cast info, media files must strictly follow structured paths, such as:
   `Movies/The Matrix (1999)/The Matrix (1999).mkv` or `TV/Frieren (2023)/Season 01/Frieren S01E01.mkv`.
2. **Torrent clients require immutable seeding directories:** files in `Downloads` must preserve their original names, directory hierarchy, and checksums to keep active seeds and maintain tracker ratios.

### The Solution: Atomic Hardlinks (TRaSH Guides)
The community standard for resolving this conflict is the methodology defined by [TRaSH Guides: Hardlinks and Instant Moves](https://trash-guides.info/Hardlinks/Hardlinks-and-Instant-Moves/).

When the download directory (`Downloads`) and media library (`Media`) reside on the **same physical filesystem partition**, files do not need to be copied or moved. Instead, hardlinks (`os.link`) create a second filesystem pointer to the exact same physical inode:
* Disk space is **never duplicated** (Zero-Copy).
* The torrent client continues seeding without interruption from `Downloads`.
* The media server indexes a pristine, clean library structure in `Media`.

```text
       Physical file on disk (ext4, Inode #482910)
                      ▲                ▲
                      │                │
             [Hardlink 1]         [Hardlink 2]
         /storage/Downloads/      /storage/Media/Movies/
         The.Matrix.1999.BDRip    The Matrix (1999)/The Matrix (1999).mkv
         (Seeding on tracker)     (Cataloged by Jellyfin / Plex)
```

### Why an AI Agent?
Torrent releases rarely arrive in clean packages. In reality, they are chaotic:
* Transliterated or Japanese romaji titles (`Koukaku Kidoutai (2026) [WEB-DL 1080p]`).
* Companion audio tracks (`.mka`) and subtitle files (`.ass`) scattered alongside font folders (`.ttf`).
* Rigid regex-based automation tools (Sonarr, Radarr) frequently fail on irregular anime releases, multi-audio releases, or audiobooks.

**The Antigravity AI Agent (`agy`) handles the complex heavy lifting:**
1. Parses unstructured release names and matches them with canonical records on IMDb, TMDb, or Wikipedia.
2. Analyzes release contents: understands which audio tracks and subtitles correspond to which episodes, and invokes `muxpress` (`mkvmerge`) to assemble monolithic MKV containers losslessly.
3. Instantly builds a TRaSH-compliant folder hierarchy using atomic `os.link` calls.

---

## Why Docker Engine Instead of Docker Sandboxes (SBX)

While Docker Sandboxes (`sbx`) was initially considered, adopting standard **Docker Engine** is a deliberate engineering decision:

* **Direct Hardware GPU Passthrough:** SBX isolates workloads inside microVMs that lack device node passthrough for host GPUs. Hardware video compression in **AV1** and **HEVC** on AMD (Radeon RX 7000 via `/dev/dri`) or NVIDIA (CUDA NVENC) is physically impossible inside SBX. Docker Engine passes GPU devices directly without virtualization overhead.
* **Kernel-Level Network Isolation as an SBX Replacement:** To replace the network isolation mechanism of Docker Sandboxes, the container runs with `--network=none` (no `eth0` interface, zero direct network access, physically impossible to bypass at the kernel level). Egress traffic is strictly tunneled through an ephemeral Unix domain socket to an in-memory allowlist proxy ([core/proxy.py](core/proxy.py)). It blocks container access to private LAN subnets (`192.168.x.x`, `10.x.x.x`, router, and host) while allowing requests only to Google APIs and metadata providers, without requiring root privileges or iptables rules on the host.
* **Zero-Copy I/O Performance:** Direct mounting of a single storage root (`/storage:rw`) allows the Linux kernel to perform atomic hardlinks in milliseconds without cross-device boundaries.

---

## Security Architecture

```text
 ┌─────────────────────────────────────────────────────────────┐
 │                           Host                              │
 │                                                             │
 │   Protected Host Resources (Inaccessible to container):     │
 │   - Home directory (~/.ssh, ~/.gnupg, ~/.docker)            │
 │   - Root filesystem (/) and Docker Daemon Socket            │
 │                                                             │
 │   Local allowlist proxy (operate runner):                   │
 │   - Allowed: Google Gemini API, IMDb, TMDb, Wikipedia       │
 │   - Blocked: Home LAN (192.168.x.x, 10.x.x.x), host IP      │
 └───────────────────────────────┬─────────────────────────────┘
                                 │ HTTP CONNECT Tunnel
                                 │ host.docker.internal:<port>
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │               Antigravity Operator Container                │
 │               (Base: antigravity-sbx-patched)               │
 │                                                             │
 │   - Non-privileged user: 'agent' (UID 1000, no-new-privs)   │
 │   - Raw sockets dropped: --cap-drop=NET_RAW                 │
 │   - Clean RAM scratchpad: --tmpfs=/tmp:rw,size=4g           │
 │   - Accelerator: /dev/dri/renderD128 (AMD VA-API AV1/HEVC)  │
 │   - Limits: memory=8g, cpus=4, pids-limit=4096, Tini init   │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                                 │  os.link(src, dst)
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │           Physical Storage Partition (/storage)             │
 │                                                             │
 │   /storage/Downloads/ ──[Hardlink (same inode)]──► /storage/│
 │   (Torrents seeding)                                 Media/ │
 └─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Host Diagnostics
```bash
bin/operate doctor
```
Audits Docker Engine, detects host GPUs (AMD Radeon VA-API, NVIDIA NVENC), checks **AV1** hardware support, Gemini authentication status, and recipe catalogs.

### 2. Antigravity AI Agent Authentication
The operator is fully self-contained and **does not require Antigravity installed on the host**. Credentials, OAuth tokens, and settings persist inside the shared host directory `~/.gemini` (mounted directly to `/home/agent/.gemini` in the container):
* **Configure Authentication (API Key or Google OAuth):**
  ```bash
  bin/operate login
  ```
  Allows you to enter your Gemini API Key (get a free key at https://aistudio.google.com/apikey) or authenticate with Google OAuth. Credentials are automatically stored in `~/.gemini` and utilized across all subsequent runs.
* **Quickly Save API Key via CLI flag:**
  ```bash
  bin/operate login --key="AIzaSy..."
  ```
* **Or via Environment Variable:**
  ```bash
  export GEMINI_API_KEY="AIzaSy..."
  # or pass runtime flag: bin/operate run ... --api-key="AIzaSy..."
  ```
* **Check Status or Logout:**
  ```bash
  bin/operate login --status
  bin/operate login --logout
  ```

### 3. Running Recipes

* **Library Organization (Zero-Copy Hardlinks):**
  Instantly links downloads to your media library with IMDb canonical title resolution:
  ```bash
  bin/operate run media-link /mnt/storage/Downloads/The.Matrix.1999 /mnt/storage/Media/Movies
  ```

* **Lossless Stream and Font Remuxing (Remux):**
  Combines video streams, companion audio tracks (`.mka`), subtitles (`.ass`), and embedded fonts into a single MKV container without video re-encoding:
  ```bash
  bin/operate run media-remux /mnt/storage/Downloads/Attack.on.Titan /mnt/storage/Media/TV
  ```

* **Hardware AV1 Compression on AMD Radeon RX 7700 XT:**
  Engages the hardware AV1 encoder (`av1_vaapi`) with Rollback Guard (if the compressed stream is larger than original, temporary files are destroyed):
  ```bash
  bin/operate run media-compress /mnt/storage/Media/TV/Frieren --codec av1 --quality 28
  ```

* **Completely Airgapped Execution (`--offline`):**
  Runs with `--network=none` for deterministic, offline operations:
  ```bash
  bin/operate run media-link /mnt/storage/Downloads/Series /mnt/storage/Media/TV --offline
  ```

### 4. Container Image Build
Derives downstream from `ghcr.io/retr0xcc/antigravity-sbx-patched:latest`:
* **Remote (Automated):** Handled via GitHub Actions [.github/workflows/build-and-publish.yml](.github/workflows/build-and-publish.yml).
* **Local (Optional):** When modifying recipes or container dependencies locally:
  ```bash
  bin/operate build
  ```

---

## Available Recipes

| Recipe | Description | Resource Footprint | Duration |
| :--- | :--- | :--- | :--- |
| **`media-link`** | TRaSH Guides folder hierarchy via Zero-Copy hardlinks | 0% GPU, 0% CPU | ~5–10s |
| **`media-remux`** | Lossless audio/subtitles/fonts container muxing (`-c copy`) | No re-encoding | ~20–40s |
| **`media-compress`**| Hardware AV1 / HEVC compression with Rollback Guard | GPU (AMD VA-API / NVENC) | Proportional |
| **`media-pipeline`**| End-to-end multi-stage pipeline (Link + Remux + Compress) | Configurable | Full cycle |

---

## CLI Reference

```text
operate run <recipe> <source> [destination] [options]
```

| Option | Default | Description |
| :--- | :--- | :--- |
| `recipe` | — | Recipe name (`media-link`, `media-remux`, `media-compress`, `media-pipeline`) |
| `source` | — | Source folder in `Downloads` or `Media` |
| `destination` / `-d` | Auto-detect | Target library category folder (`Movies`, `TV`, `Books`) |
| `--codec` | `auto` | Target video codec: `auto` (AV1 for RDNA 3/Ada, HEVC for older), `av1`, `hevc`, `h264` |
| `--backend` | `auto` | Encoder backend: `auto` (AMD/Intel `vaapi`, NVIDIA `nvenc`, CPU `software`) |
| `--device` | Auto-detect | Custom DRI render node path (e.g. `/dev/dri/renderD128`) |
| `-q`, `--quality` | `28` | Compression quality (CQP global_quality for VA-API, QP for NVENC, CRF for CPU) |
| `--preset` | `p6` | Encoder speed/quality preset |
| `--remux` | `false` | Mux external companion audio, subtitles, and fonts into single `.mkv` |
| `--compress` | `false` | Enable GPU hardware compression |
| `--force` | `false` | Force re-encoding even if video stream is already in target codec |
| `--max-bitrate` | — | Bitrate threshold in kbps (e.g. `4500`): re-encode files exceeding this value |
| `--offline` | `false` | Run with `--network=none` and local regex title resolution |
| `--no-proxy` | `false` | Bypass local allowlist proxy and allow unconstrained network access |
| `--api-key` | `env` | Gemini API key (alternative to `bin/operate login`) |
| `--dry-run` | `false` | Dry-run simulation: run agent in read-only mode (`/storage:ro`) to print execution plan |
| `--auto` | `false` | Unattended automated execution without interactive prompts |

---

## Hardware GPU Acceleration

* **AMD Radeon:** RX 7000 Series (RDNA 3 / Navi 3x, including Radeon RX 7700 XT) with **AV1** (`av1_vaapi`) and **HEVC** (`hevc_vaapi`) via Mesa VA-API on `/dev/dri/renderD128`.
* **NVIDIA:** GeForce GTX 10xx, RTX 20xx/30xx/40xx with NVIDIA driver and NVIDIA Container Toolkit.
* **Intel:** Arc / Iris Xe via QuickSync / VA-API.

> [!NOTE]
> Testing and profiling were performed on an **AMD Radeon RX 7700 XT** (Linux, Mesa VA-API). NVIDIA and Intel support is designed into the architecture and validated via command generation test suites, but has not been tested on physical NVIDIA/Intel hardware due to unavailability of these devices.

---

## License & Disclaimers

* Source code is distributed under the **[MIT License](LICENSE)** (© 2026 Retr0xCC).
* **Disclaimer**: This is an independent community project. It is not affiliated with, sponsored by, or endorsed by Google LLC or Docker, Inc. "Google Antigravity" is a trademark of Google LLC. "Docker" is a trademark of Docker, Inc.
