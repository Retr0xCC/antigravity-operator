**English** | [Русский](README.ru.md)

# Antigravity Operator

> Lightweight host launcher and plan executor for Plex/Jellyfin libraries ([TRaSH Guides](https://trash-guides.info/Hardlinks/Hardlinks-and-Instant-Moves/)), built to work with an isolated Docker Sandbox (SBX) Mixin Kit.

[![CLI: operate](https://img.shields.io/badge/CLI-operate-blue.svg)](bin/operate)
[![Base: antigravity-sbx-patched](https://img.shields.io/badge/Base-antigravity--sbx--patched-blueviolet.svg)](https://github.com/Retr0xCC/antigravity-sbx-patched)
[![Runtime: Docker Sandboxes (SBX)](https://img.shields.io/badge/Runtime-Docker%20Sandboxes%20(SBX)-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/)
[![GPU: AMD AV1 & NVIDIA NVENC](https://img.shields.io/badge/GPU-AMD%20AV1%20%7C%20NVENC-ED1C24?logo=amd&logoColor=white)](#hardware-gpu-acceleration)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Architecture: RO Sandbox → Plan → Native Host Execution

The previous monolithic container model has been replaced with a clean two-phase pipeline:

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │ 1. PLANNING PHASE (Docker Sandbox microVM / SBX Kit)                   │
 │    - Raw torrent downloads mounted strictly READ-ONLY (:ro)            │
 │    - Agent (agy) inspects streams via ffprobe and mkvmerge             │
 │    - Outbound network locked to strict metadata allowlist              │
 │    - Writes output plan to dedicated RW folder: plan.json, summary.md  │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ 2. EXECUTION PHASE (Native Host execution with user permissions)       │
 │    - Human reviews clear summary.md before applying                    │
 │    - Host runner safely executes plan.json (shell=False)               │
 │    - Zero-copy hardlinks (os.link) per TRaSH Guides                    │
 │    - Native hardware GPU transcoding (AMD VA-API AV1/HEVC, NVENC)      │
 │    - Continuous torrent seeding remains uninterrupted                  │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Check Host Readiness
```bash
bin/operate doctor
```

### 2. Full Workflow (Plan + Review + Interactive Apply)
```bash
bin/operate run /mnt/storage/Downloads/Torrents/Sousou_no_Frieren --dest /mnt/storage/Media/TV
```

### 3. Step-by-Step Workflow
```bash
# 1. Generate plan without applying
bin/operate plan /mnt/storage/Downloads/Torrents/Sousou_no_Frieren --dest /mnt/storage/Media/TV --out ./out

# 2. Review summary
cat ./out/summary.md

# 3. Apply verified plan on host
bin/operate apply ./out/plan.json
```
