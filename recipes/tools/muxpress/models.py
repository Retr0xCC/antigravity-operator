"""Data models for Muxpress."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TrackType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    FONT = "font"


@dataclass(frozen=True)
class Track:
    """Represents an external or internal media track."""

    path: Path
    type: TrackType
    language: str
    title: str
    stream_index: int = 0


@dataclass(frozen=True)
class FontAttachment:
    """Represents a font to attach to an MKV file."""

    path: Path
    mime_type: str


@dataclass
class EpisodePlan:
    """Complete plan for assembling an individual episode or standalone movie/OVA."""

    source_video: Path
    season: int | None
    episode: int | None
    title: str
    output_path: Path
    audio_tracks: list[Track] = field(default_factory=list)
    subtitle_tracks: list[Track] = field(default_factory=list)
    fonts: list[FontAttachment] = field(default_factory=list)
    files_to_delete: list[Path] = field(default_factory=list)

    @property
    def formatted_code(self) -> str:
        """Return SxxExx, Exx, or Movie/OVA descriptor."""
        if self.season is not None and self.episode is not None:
            return f"S{self.season:02d}E{self.episode:02d}"
        if self.episode is not None:
            return f"E{self.episode:02d}"
        return "Movie/OVA"


@dataclass
class EncoderSettings:
    """Flexible settings for hardware (VA-API / NVENC) and software video encoders."""

    backend: str = "vaapi"  # "vaapi", "nvenc", "qsv", "software"
    codec: str = "av1"      # "av1", "hevc", "h264"
    preset: str = "p6"
    quality: int = 28       # Unified parameter: global_quality (VA-API), qp (NVENC), crf (CPU)
    device: str | None = None  # e.g. "/dev/dri/renderD128" for VA-API, "0" for NVENC
    force_reencode: bool = False
    qp: int = 28
    gpu: int = 0
    force_hevc: bool = False

    def __post_init__(self):
        # Sync backward-compatible fields
        if self.qp != 28 and self.quality == 28:
            self.quality = self.qp
        elif self.quality != 28 and self.qp == 28:
            self.qp = self.quality

        if self.force_hevc:
            self.force_reencode = True
        elif self.force_reencode:
            self.force_hevc = True


@dataclass
class PipelineConfig:
    """Global configuration for a muxpress execution run."""

    target_path: Path = field(default_factory=lambda: Path("."))
    output_dir: Path = field(default_factory=lambda: Path("merge-output"))
    custom_title: str | None = None
    custom_season: int | None = None
    episode_offset: int = 0
    merge_only: bool = False
    compress_only: bool = False
    dry_run: bool = False
    delete_sources: bool = False
    interactive: bool = False
    verbose: bool = False
    encoder: EncoderSettings = field(default_factory=EncoderSettings)

    def __init__(
        self,
        target_path: Path | None = None,
        output_dir: Path = Path("merge-output"),
        custom_title: str | None = None,
        custom_season: int | None = None,
        episode_offset: int = 0,
        merge_only: bool = False,
        compress_only: bool = False,
        dry_run: bool = False,
        delete_sources: bool = False,
        interactive: bool = False,
        verbose: bool = False,
        encoder: EncoderSettings | None = None,
        target_dir: Path | None = None,
        no_compress: bool = False,
    ):
        if target_path is not None:
            self.target_path = target_path
        elif target_dir is not None:
            self.target_path = target_dir
        else:
            self.target_path = Path(".")

        self.output_dir = output_dir
        self.custom_title = custom_title
        self.custom_season = custom_season
        self.episode_offset = episode_offset
        self.merge_only = merge_only or no_compress
        self.compress_only = compress_only
        self.dry_run = dry_run
        self.delete_sources = delete_sources
        self.interactive = interactive
        self.verbose = verbose
        self.encoder = encoder if encoder is not None else EncoderSettings()

    @property
    def is_file(self) -> bool:
        """True if target_path points to an existing regular file."""
        return self.target_path.is_file()

    @property
    def target_dir(self) -> Path:
        """Return directory path (either target_path if it's a dir, or target_path.parent)."""
        return self.target_path if self.target_path.is_dir() else self.target_path.parent

    @property
    def no_compress(self) -> bool:
        """Backward-compatible alias for merge_only."""
        return self.merge_only
