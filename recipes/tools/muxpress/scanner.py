"""Scanner and matcher for media files, audio/subs tracks, and fonts."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .models import EpisodePlan, FontAttachment, Track, TrackType

# Extensions supported for audio and subtitles
AUDIO_EXTENSIONS = {".mka", ".ac3", ".aac", ".dts", ".flac", ".wav", ".mp3", ".eac3", ".m4a"}
SUBTITLE_EXTENSIONS = {".ass", ".srt", ".vtt", ".ssa"}
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}

# Standard folder names to ignore as release groups
RESERVED_SUBFOLDERS = {"fonts", "шрифты", "attachments"}

# Ordered filename regex patterns for Season & Episode detection
FILENAME_PATTERNS = [
    # 1. Title_S01E05 or Title.s1e5
    re.compile(r"^(?P<title>.+?)[ _.\-]+[sS](?P<season>\d+)[eE](?P<episode>\d+)", re.IGNORECASE),
    # 2. Title S1 - 05
    re.compile(r"^(?P<title>.+?)\s+[sS](?P<season>\d+)\s*-\s*(?P<episode>\d+)", re.IGNORECASE),
    # 3. Title 01 [05] (Season [Episode])
    re.compile(r"^(?P<title>.+?)\s+(?P<season>\d+)\s+\[(?P<episode>\d+)\]"),
    # 4. Title [05] (Episode only -> Season 1)
    re.compile(r"^(?P<title>.+?)\s+\[(?P<episode>\d+)\]"),
    # 5. Title 01 - 05 (Season - Episode)
    re.compile(
        r"^(?P<title>.+?)\s+(?P<season>\d+)[ _.\-]+(?P<episode>\d+)(?![pP])(?:\s*(?:v\d+|END))?(?:\s*\([^)]+\))?(?:\s*\[[^\]]+\])*$",
        re.IGNORECASE,
    ),
    # 6. Title - 05 (Episode only -> Season 1)
    re.compile(
        r"^(?P<title>.+?)[ _.\-]+(?P<episode>\d+)(?![pP])(?:\s*(?:v\d+|END))?(?:\s*\([^)]+\))?(?:\s*\[[^\]]+\])*$",
        re.IGNORECASE,
    ),
    # 7. Classical Anime: Show Name - 01 (1080p) or Show Name - 01 [1080p]
    re.compile(
        r"^(?P<title>.+?)\s*-\s*(?P<episode>\d+)(?:\s*(?:v\d+|END))?(?:\s*\([^)]+\))?(?:\s*\[[^\]]+\])*$",
        re.IGNORECASE,
    ),
]


def clean_filename_stem(stem: str) -> str:
    """Strip leading release group tags such as '[SubsPlease] ' or '[Erai-raws]'."""
    return re.sub(r"^\[[^\]]+\]\s*", "", stem).strip()


def clean_technical_parameters(stem: str) -> str:
    """Clean technical parameters and non-episode tags from filename stem.

    Removes tags in [...], resolutions like 1080p, 1920x1080, codecs and rip terms,
    while preserving actual episode numbers.
    """
    # 1. Strip bracketed tags that are not pure episode digits
    def replace_bracket(m: re.Match) -> str:
        content = m.group(1).strip()
        # Keep if purely 1-4 digits (like [01], [05], [1080]) and not resolution like 1920
        if re.match(r"^\d{1,4}$", content) and content != "1920":
            return m.group(0)
        return ""

    res = re.sub(r"\[([^\]]+)\]", replace_bracket, stem)

    # 2. Strip parenthesized tech tags (e.g. (1080p), (1920x1080), (BDRip 1080p))
    res = re.sub(
        r"\s*\([^)]*(?:1080|720|2160|bdrip|webrip|remux|hevc|x264|x265|1920x1080|bluray|blu-ray|hdtv|dvdrip)[^)]*\)",
        "",
        res,
        flags=re.IGNORECASE,
    )

    # 3. Strip standalone resolution dimensions (1920x1080, 1280x720, etc.)
    res = re.sub(r"(?i)(^|[\s_.\-\(\[])\d{3,4}x\d{3,4}($|[\s_.\-\)\]])", r"\1 \2", res)

    # 4. Strip standalone resolution with p/i (1080p, 720p, etc.)
    res = re.sub(r"(?i)(^|[\s_.\-\(\[])\d{3,4}[pi]($|[\s_.\-\)\]])", r"\1 \2", res)

    # 5. Strip standalone codec/quality keywords
    res = re.sub(
        r"(?i)(^|[\s_.\-\(\[])(?:bdrip|webrip|web-dl|bluray|blu-ray|hdtv|dvdrip|remux|hevc|h\.?265|x265|h\.?264|x264|avc|10bit|10-bit)($|[\s_.\-\)\]])",
        r"\1 \2",
        res,
    )

    # Strip leftover trailing/leading whitespace and duplicate spaces
    res = re.sub(r"\s+", " ", res).strip(" -_.")
    return res


def parse_episode_filename(stem: str, allow_fallback: bool = False) -> tuple[str, int | None, int | None] | None:
    """Parse title, season, and episode numbers from a filename stem.

    If allow_fallback is True (used for standalone movies / OVAs), returns (title, None, None)
    if no standard season/episode pattern is found.
    """
    clean = clean_filename_stem(stem)
    sanitized = clean_technical_parameters(clean)

    for pattern in FILENAME_PATTERNS:
        match = pattern.search(sanitized)
        if match:
            groups = match.groupdict()
            raw_title = groups.get("title", "").strip(" -_.")
            season_str = groups.get("season")
            episode_str = groups.get("episode")

            if not episode_str:
                continue

            season = int(season_str) if season_str else 1
            episode = int(episode_str)
            cleaned_title = raw_title.replace("_", " ")
            title = re.sub(r"\s+", " ", cleaned_title).strip()
            return title, season, episode

    if allow_fallback:
        cleaned_movie = sanitized.replace("_", " ")
        title = re.sub(r"\s+", " ", cleaned_movie).strip(" -_.")
        return (title if title else clean, None, None)

    return None


def detect_folder_language(folder_name: str) -> str:
    """Detect language code (rus, eng, jpn, etc.) from folder or filename."""
    name_lower = folder_name.lower()
    if any(k in name_lower for k in ("eng", "en.", "en_", "en-", "en ", "english")):
        return "eng"
    if any(k in name_lower for k in ("jpn", "jap", "ja.", "ja_", "ja-", "japanese")):
        return "jpn"
    if any(k in name_lower for k in ("rus", "ru.", "ru_", "ru-", "ru ", "russian", "sound", "sub", "шрифт")):
        return "rus"
    return "rus"


def detect_release_group_from_name(file_stem: str, base_stem: str) -> str | None:
    """Extract release group name from brackets in a track file stem."""
    # Remove the base stem prefix to inspect suffix tokens
    suffix = file_stem[len(base_stem):].strip(" -_.") if file_stem.startswith(base_stem) else file_stem

    # Check for [Group] or (Group)
    bracket_match = re.search(r"\[([^\]]+)\]|\(([^)]+)\)", suffix)
    if bracket_match:
        cand = (bracket_match.group(1) or bracket_match.group(2)).strip()
        # Filter out resolution or audio codec tokens
        cand_lower = cand.lower()
        if not any(k in cand_lower for k in ("1080", "720", "2160", "bdrip", "webrip", "aac", "ac3", "flac", "rus", "eng")):
            return cand
    return None


def discover_sibling_tracks(
    video_file: Path,
    base_stem: str,
) -> tuple[list[Track], list[Track], list[Path]]:
    """Discover audio and subtitle tracks located directly alongside the video file (siblings)."""
    audio_tracks: list[Track] = []
    sub_tracks: list[Track] = []
    files_to_delete: list[Path] = []

    parent_dir = video_file.parent
    if not parent_dir.is_dir():
        return audio_tracks, sub_tracks, files_to_delete

    clean_base = clean_filename_stem(base_stem)

    for entry in sorted(parent_dir.iterdir()):
        if not entry.is_file() or entry == video_file or entry.name.endswith(".temp.mkv"):
            continue

        ext = entry.suffix.lower()
        is_audio = ext in AUDIO_EXTENSIONS
        is_sub = ext in SUBTITLE_EXTENSIONS

        if not (is_audio or is_sub):
            continue

        entry_stem = entry.stem
        # Check if the sibling file matches the video file stem
        if entry_stem == base_stem or entry_stem.startswith(f"{base_stem}.") or entry_stem.startswith(f"{base_stem}_") or entry_stem.startswith(f"{base_stem} ") or (clean_base and clean_base in entry_stem):
            lang = detect_folder_language(entry_stem)
            group = detect_release_group_from_name(entry_stem, base_stem)
            title = f"{group} ({lang})" if group else f"Default ({lang})"

            if is_audio:
                audio_tracks.append(Track(path=entry, type=TrackType.AUDIO, language=lang, title=title))
            else:
                sub_tracks.append(Track(path=entry, type=TrackType.SUBTITLE, language=lang, title=title))

            files_to_delete.append(entry)

    return audio_tracks, sub_tracks, files_to_delete


def discover_track_directories(target_dir: Path) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """Scan target_dir for sound and subtitle directories with their language codes."""
    sound_dirs: list[tuple[Path, str]] = []
    subs_dirs: list[tuple[Path, str]] = []

    known_sound_names = {
        "rus sound", "ru sounds", "ru sound", "rus sounds", "sounds", "sound",
        "eng sound", "eng sounds", "eng-sound", "jpn sound", "jpn sounds",
    }
    known_subs_names = {
        "rus subs", "ru subs", "ru sub", "rus sub", "subs", "sub",
        "eng subs", "eng sub", "eng-subs", "jpn subs", "jpn sub",
    }

    if not target_dir.is_dir():
        return sound_dirs, subs_dirs

    for entry in target_dir.iterdir():
        if not entry.is_dir():
            continue

        lower_name = entry.name.lower()

        if lower_name in known_sound_names or (("sound" in lower_name or "озвучк" in lower_name) and "font" not in lower_name):
            lang = detect_folder_language(entry.name)
            sound_dirs.append((entry, lang))
        elif lower_name in known_subs_names or (("sub" in lower_name or "саб" in lower_name) and "font" not in lower_name):
            lang = detect_folder_language(entry.name)
            subs_dirs.append((entry, lang))

    return sound_dirs, subs_dirs


def _matches_file(
    file_path: Path,
    base_stem: str,
    season: int | None,
    episode: int | None,
    valid_extensions: set[str],
) -> bool:
    """Check if file matches the target episode by exact base stem, name, or episode number.

    Requires an exact match by episode number or name; otherwise returns False.
    """
    if file_path.suffix.lower() not in valid_extensions:
        return False

    file_stem = file_path.stem

    # 1. Exact base match
    if file_stem == base_stem or file_stem.startswith(f"{base_stem}."):
        return True

    clean_base = clean_filename_stem(base_stem)
    clean_file = clean_filename_stem(file_stem)

    # 2. Match by name:
    # If the clean names match or clean_base / clean_file correspond
    if clean_base and (
        clean_file == clean_base
        or clean_file.startswith(f"{clean_base}.")
        or clean_file.startswith(f"{clean_base} ")
        or clean_file.startswith(f"{clean_base}_")
        or clean_base in clean_file
        or (len(clean_file) > 3 and clean_file in clean_base)
    ):
        # But if both track and video have parsed episode numbers, ensure they match!
        track_parsed = parse_episode_filename(file_stem, allow_fallback=True)
        if track_parsed and track_parsed[2] is not None and episode is not None:
            if track_parsed[2] != episode:
                return False
        return True

    # 3. Match by episode number:
    # ONLY if episode is known (not None)! If episode is None (e.g. Movie/OVA/Special without episode number),
    # it CANNOT match by episode number.
    if episode is not None:
        # Check if the video is a special (e.g. contains 'missing link', 'special', 'ova', 'movie')
        # If the video is a special, regular episode audio tracks without the special name MUST NOT match!
        base_lower = clean_base.lower()
        is_special = any(sp in base_lower for sp in ("missing link", "special", "ova", "movie", "film"))
        if is_special:
            file_lower = clean_file.lower()
            if not any(sp in file_lower for sp in ("missing link", "special", "ova", "movie", "film")):
                return False

        s_val = season if season is not None else 1
        patterns = [
            re.compile(rf"[sS]0?{s_val}[eE]0?{episode}(?:[^\d]|$)", re.IGNORECASE),
            re.compile(rf"[sS]0?{s_val}.*?ep\.?0?{episode}(?:[^\d]|$)", re.IGNORECASE),
            re.compile(rf"(?:[ _\.\-]0?{episode}(?:[^\d]|$)|\[0?{episode}\])"),
        ]
        if any(p.search(file_stem) for p in patterns):
            # If the audio track also has a season indicator, make sure it matches
            audio_season_match = re.search(r"[sS](\d+)", file_stem)
            if audio_season_match:
                audio_s = int(audio_season_match.group(1))
                if season is not None and audio_s != season:
                    return False
            return True

    return False


def match_tracks_in_dir(
    search_dir: Path,
    base_stem: str,
    season: int | None,
    episode: int | None,
    lang: str,
    track_type: TrackType,
) -> tuple[list[Track], list[Path]]:
    """Match tracks in search_dir using flat and nested release group structure."""
    tracks: list[Track] = []
    files_to_delete: list[Path] = []
    valid_exts = AUDIO_EXTENSIONS if track_type == TrackType.AUDIO else SUBTITLE_EXTENSIONS

    if not search_dir.is_dir():
        return tracks, files_to_delete

    # 1. Flat structure
    flat_matches = [
        f for f in sorted(search_dir.iterdir())
        if f.is_file() and _matches_file(f, base_stem, season, episode, valid_exts)
    ]
    if flat_matches:
        chosen = flat_matches[0]
        title = f"Default ({lang})"
        tracks.append(Track(path=chosen, type=track_type, language=lang, title=title))
        files_to_delete.append(chosen)

    # 2. Nested structure
    for sub_dir in sorted(search_dir.iterdir()):
        if not sub_dir.is_dir() or sub_dir.name.lower() in RESERVED_SUBFOLDERS:
            continue

        group_name = sub_dir.name
        nested_matches = [
            f for f in sorted(sub_dir.iterdir())
            if f.is_file() and _matches_file(f, base_stem, season, episode, valid_exts)
        ]
        if nested_matches:
            chosen = nested_matches[0]
            title = f"{group_name} ({lang})"
            tracks.append(Track(path=chosen, type=track_type, language=lang, title=title))
            files_to_delete.append(chosen)

    return tracks, files_to_delete


def discover_fonts(target_dir: Path, exclude_dir: Path | None = None) -> list[FontAttachment]:
    """Find and deduplicate font files in target_dir and its subdirectories."""
    fonts: list[FontAttachment] = []
    seen_keys: set[tuple[str, int]] = set()

    if not target_dir.is_dir():
        return fonts

    exclude_resolved = exclude_dir.resolve() if exclude_dir else None
    target_resolved = target_dir.resolve()

    for root, dirs, files in os.walk(target_dir):
        root_path = Path(root)

        # Skip output dir
        if exclude_resolved and (root_path == exclude_resolved or exclude_resolved in root_path.parents):
            continue

        is_root = (root_path.resolve() == target_resolved)
        is_font_folder = any(k in root_path.name.lower() for k in ("font", "шрифт", "attachment"))

        for file_name in sorted(files):
            ext = Path(file_name).suffix.lower()
            # Pick font if it is in a font folder OR directly in the root target directory
            if ext in FONT_EXTENSIONS and (is_font_folder or is_root):
                font_path = root_path / file_name
                try:
                    size = font_path.stat().st_size
                except OSError:
                    continue

                key = (font_path.name.lower(), size)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                mime = "application/vnd.ms-opentype" if ext == ".otf" else "application/x-truetype-font"
                fonts.append(FontAttachment(path=font_path, mime_type=mime))

    return fonts


def build_episode_plan(
    video_file: Path,
    target_dir: Path,
    output_dir: Path,
    sound_dirs: list[tuple[Path, str]],
    subs_dirs: list[tuple[Path, str]],
    fonts: list[FontAttachment],
    custom_title: str | None = None,
    custom_season: int | None = None,
    episode_offset: int = 0,
    allow_fallback: bool = False,
) -> EpisodePlan | None:
    """Build an EpisodePlan for a single video file or standalone movie/OVA."""
    parsed = parse_episode_filename(video_file.stem, allow_fallback=allow_fallback)
    if not parsed:
        return None

    raw_title, parsed_season, parsed_episode = parsed
    title = custom_title if custom_title else raw_title
    season = custom_season if custom_season is not None else parsed_season
    episode = parsed_episode

    if episode is not None and episode_offset > 0:
        episode = episode - episode_offset
        if episode < 1:
            episode = parsed_episode

    # Determine output file path
    if season is not None and episode is not None:
        season_pad = f"{season:02d}"
        ep_pad = f"{episode:02d}"
        output_path = output_dir / f"{title} S{season_pad}E{ep_pad}.mkv"
    elif episode is not None:
        ep_pad = f"{episode:02d}"
        output_path = output_dir / f"{title} E{ep_pad}.mkv"
    else:
        output_path = output_dir / f"{title}.mkv"

    all_audio: list[Track] = []
    all_subs: list[Track] = []
    files_to_delete: list[Path] = [video_file]

    base_stem = video_file.stem

    # 1. Discover sibling tracks located alongside video_file
    sib_audio, sib_subs, del_sibs = discover_sibling_tracks(video_file, base_stem)
    all_audio.extend(sib_audio)
    all_subs.extend(sib_subs)
    files_to_delete.extend(del_sibs)

    seen_audio_paths = {t.path.resolve() for t in all_audio}
    seen_subs_paths = {t.path.resolve() for t in all_subs}

    # 2. Match audio tracks across all sound folders
    for s_dir, lang in sound_dirs:
        matched_audio, del_audio = match_tracks_in_dir(
            s_dir, base_stem, season, episode, lang, TrackType.AUDIO
        )
        for t in matched_audio:
            if t.path.resolve() not in seen_audio_paths:
                all_audio.append(t)
                seen_audio_paths.add(t.path.resolve())
        files_to_delete.extend(del_audio)

    # 3. Match subtitle tracks across all sub folders
    for sub_dir, lang in subs_dirs:
        matched_subs, del_subs = match_tracks_in_dir(
            sub_dir, base_stem, season, episode, lang, TrackType.SUBTITLE
        )
        for t in matched_subs:
            if t.path.resolve() not in seen_subs_paths:
                all_subs.append(t)
                seen_subs_paths.add(t.path.resolve())
        files_to_delete.extend(del_subs)

    # Unique files to delete
    unique_files_to_delete = list(dict.fromkeys(files_to_delete))

    return EpisodePlan(
        source_video=video_file,
        season=season,
        episode=episode,
        title=title,
        output_path=output_path,
        audio_tracks=all_audio,
        subtitle_tracks=all_subs,
        fonts=fonts,
        files_to_delete=unique_files_to_delete,
    )
