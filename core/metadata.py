"""Metadata enrichment and search integration (IMDb, TMDB, Wikipedia, Cyclopedia).

Provides title cleaning and online/offline canonical metadata resolution for movies,
series, anime, and audiobooks.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any


USER_AGENT = "AntigravityOperator/1.0 (Headless Media Pipeline)"


def clean_title_tokens(raw_name: str) -> tuple[str, str | None, str]:
    """Clean technical tags, resolution, codecs, and release groups from name.

    Returns:
        (clean_title, year_or_none, category_guess)
    """
    stem = raw_name.strip()

    # 1. Strip bracketed groups like [SubsPlease], [Erai-raws], [1080p]
    stem = re.sub(r"^\[[^\]]+\]\s*", "", stem)

    # 2. Extract year (19xx or 20xx)
    year_match = re.search(r"[\s_.\-(](19\d\d|20\d\d)[\s_.\-)]", stem)
    year = year_match.group(1) if year_match else None

    # 3. Detect category guess
    cat = "movie"
    if re.search(r"[sS]\d+[eE]\d+|season|сезон|ep\d+|episode| - \d{2,4}\b", stem, re.IGNORECASE):
        cat = "tv"
    elif re.search(r"audiobook|аудиокнига|книга|mp3|m4b|narrat|читает|автор", stem, re.IGNORECASE):
        cat = "book"

    # 4. Strip technical parameters
    tech_pattern = (
        r"(?i)(1080p|720p|2160p|4k|1920x1080|1280x720|bdrip|webrip|web-dl|bluray|"
        r"blu-ray|hdtv|dvdrip|remux|hevc|h\.?265|x265|h\.?264|x264|avc|10bit|10-bit|"
        r"dts-hd|dts|truehd|atmos|flac|aac|ac3|ddp5\.1|dd5\.1|rus|eng|jpn|sound|subs)"
    )
    stem = re.sub(tech_pattern, " ", stem)

    # 5. Strip year from title if present
    if year:
        stem = re.sub(rf"[\s_.\-(]{year}[\s_.\-)]", " ", stem)

    # Strip remaining brackets and symbols
    stem = re.sub(r"[\[\]\(\)\{\}_.\-]+", " ", stem)
    clean_title = re.sub(r"\s+", " ", stem).strip()

    return clean_title, year, cat


def search_imdb(title: str, year: str | None = None, timeout: float = 4.0) -> tuple[str, str | None]:
    """Search IMDb suggestion API for canonical title and release year.

    Falls back cleanly to (title, year) on network error or offline mode.
    """
    if not title:
        return title, year

    query = f"{title} {year}" if year else title
    encoded = urllib.parse.quote(query)
    first_char = encoded[:1].lower() or "a"
    url = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{encoded}.json"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("d", [])
            if results:
                # Top result
                top = results[0]
                canon_title = top.get("l", title)
                canon_year = str(top.get("y", year or ""))
                return canon_title, (canon_year if canon_year else year)
    except Exception:
        # Fallback to Wikipedia API if IMDb fails
        try:
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote(query)}&limit=1&format=json"
            req = urllib.request.Request(wiki_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                titles = data[1] if len(data) > 1 else []
                if titles:
                    w_title = titles[0]
                    # Strip wiki suffixes like '(film)' or '(TV series)'
                    w_title = re.sub(r"\s*\([^)]*(film|series|anime|tv)[^)]*\)", "", w_title, flags=re.IGNORECASE).strip()
                    return w_title, year
        except Exception:
            pass

    return title, year


def search_cyclopedia_book(
    title: str,
    author: str | None = None,
    timeout: float = 4.0,
) -> tuple[str, str, str | None]:
    """Search OpenLibrary / Wikipedia / Cyclopedia for canonical book author and title.

    Returns:
        (canonical_author, canonical_title, year_or_none)
    """
    query = f"{author} {title}" if author else title
    encoded = urllib.parse.quote(query)

    try:
        url = f"https://openlibrary.org/search.json?q={encoded}&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            docs = data.get("docs", [])
            if docs:
                doc = docs[0]
                b_title = doc.get("title", title)
                authors = doc.get("author_name", [])
                b_author = authors[0] if authors else (author or "Unknown Author")
                b_year = str(doc.get("first_publish_year", "")) or None
                return b_author, b_title, b_year
    except Exception:
        pass

    return author or "Unknown Author", title, None
