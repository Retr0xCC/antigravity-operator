# ========================================================
# Antigravity Operator Media Runner
# Downstream build from Antigravity SBX Patched:
# ghcr.io/retr0xcc/antigravity-sbx-patched:latest
# ========================================================

ARG BASE_IMAGE=ghcr.io/retr0xcc/antigravity-sbx-patched:latest

FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="antigravity-operator" \
      org.opencontainers.image.description="Headless AI agent runner for media hardlinks and AV1/HEVC hardware compression"

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Install multimedia tools, AMD VA-API drivers (radeonsi), Intel VA-API, and MKV utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    mkvtoolnix \
    mediainfo \
    mesa-va-drivers \
    libva-drm2 \
    vainfo \
    jq \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Ensure operator directories and user compatibility
# User 'agent' (UID 1000) is standard in SBX. We create symlinks so both /home/operator and /home/agent resolve seamlessly.
RUN mkdir -p /storage /recipes /recipe /home/agent/.gemini /home/agent/.cache \
    && chown -R agent:agent /storage /recipes /recipe /home/agent \
    && (ln -s /home/agent /home/operator 2>/dev/null || true)

# Global wrapper for Muxpress CLI across all recipes
RUN printf '#!/bin/bash\nfor d in /recipe /recipes/tools /recipes/media-pipeline; do\n  if [ -d "$d/muxpress" ]; then\n    export PYTHONPATH="$d:$PYTHONPATH"\n    exec python3 -m muxpress "$@"\n  fi\ndone\necho "Error: muxpress engine not found" >&2\nexit 1\n' > /usr/local/bin/muxpress \
    && chmod 755 /usr/local/bin/muxpress

# Global symlink to guarantee 'agy' is found in system PATH
RUN if [ ! -f /usr/local/bin/agy ] && [ -f /home/agent/.local/bin/agy ]; then \
        ln -s /home/agent/.local/bin/agy /usr/local/bin/agy; \
    fi

USER agent
ENV HOME=/home/agent
ENV PATH="/home/agent/.local/bin:/usr/local/bin:${PATH}"
ENV TMPDIR=/tmp

WORKDIR /tmp

ENTRYPOINT ["tini", "--"]
CMD ["agy", "--dangerously-skip-permissions"]
