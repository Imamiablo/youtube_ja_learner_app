"""Utility helpers for working with Japanese text."""

from __future__ import annotations

import html
import re

KANJI_RE = re.compile(r"[\u4E00-\u9FFF]")
HIRAGANA_RE = re.compile(r"[\u3040-\u309F]")
KATAKANA_RE = re.compile(r"[\u30A0-\u30FF]")
JAPANESE_CHAR_RE = re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]")


def contains_kanji(text: str) -> bool:
    """Return True when the string contains at least one kanji character."""
    return bool(KANJI_RE.search(text or ""))


def contains_japanese(text: str) -> bool:
    """Return True when the string contains Japanese script characters."""
    return bool(JAPANESE_CHAR_RE.search(text or ""))


def katakana_to_hiragana(text: str) -> str:
    """Convert katakana text into hiragana.

    Many tokenizers return readings in katakana. Hiragana tends to be easier to
    read in furigana, so we convert it for display.
    """
    result: list[str] = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(char)
    return "".join(result)


def safe_html(text: str) -> str:
    """Escape text for safe HTML display."""
    return html.escape(text or "")


def seconds_to_timestamp(seconds: float | int) -> str:
    """Convert raw seconds into HH:MM:SS or MM:SS format."""
    total = int(seconds or 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"



def is_all_katakana(text: str) -> bool:
    """Return True when text is made only of katakana-style characters."""
    text = (text or "").strip()
    return bool(text) and bool(re.fullmatch(r"[゠-ヿー・]+", text))
