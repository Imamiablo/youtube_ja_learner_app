"""Transcript retrieval and segmentation helpers."""

import re
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

from src.utils.japanese import contains_japanese


class TranscriptService:
    """Fetch and normalize transcript data from user input."""

    def __init__(self, max_segments: int = 120) -> None:
        self.max_segments = max_segments

    def extract_video_id(self, url: str) -> str:
        """Extract a YouTube video ID from common URL formats."""
        parsed = urlparse(url)
        if parsed.hostname in {"youtu.be"}:
            return parsed.path.lstrip("/")
        if parsed.hostname and "youtube.com" in parsed.hostname:
            query = parse_qs(parsed.query)
            if "v" in query:
                return query["v"][0]
            if parsed.path.startswith("/shorts/"):
                return parsed.path.split("/shorts/")[-1].split("/")[0]
            if parsed.path.startswith("/embed/"):
                return parsed.path.split("/embed/")[-1].split("/")[0]
        raise ValueError("Could not extract a YouTube video ID from this URL.")

    def fetch_youtube_title(self, url: str) -> str:
        """Fetch a YouTube video's public title via the oEmbed endpoint."""
        endpoint = f"https://www.youtube.com/oembed?url={quote_plus(url)}&format=json"
        try:
            response = requests.get(endpoint, timeout=15)
            response.raise_for_status()
            payload = response.json()
            title = str(payload.get("title", "")).strip()
            if title:
                return title
        except requests.RequestException:
            pass
        return self.extract_video_id(url)

    def fetch_youtube_segments(self, url: str) -> list[dict[str, object]]:
        """Fetch transcript segments from YouTube.

        The service prefers Japanese transcripts. If a Japanese transcript is not
        available, it will still try the generic transcript list and then filter.
        """
        video_id = self.extract_video_id(url)

        try:
            transcript_items = self._fetch_transcript_items(video_id)
        except (NoTranscriptFound, TranscriptsDisabled):
            raise RuntimeError(
                "No Japanese YouTube transcript was found for this video. "
                "Use the manual transcript input for now."
            )

        segments: list[dict[str, object]] = []
        for item in transcript_items[: self.max_segments]:
            item_text = self._clean_segment_text(str(self._item_value(item, "text", "")))
            if not item_text:
                continue
            segments.append(
                {
                    "segment_index": len(segments),
                    "start_sec": float(self._item_value(item, "start", 0)),
                    "duration_sec": float(self._item_value(item, "duration", 0)),
                    "japanese_text": item_text,
                }
            )

        if not segments:
            raise RuntimeError("Transcript was found, but no usable segments remained after cleaning.")

        return segments

    def build_segments_from_manual_text(self, text: str) -> list[dict[str, object]]:
        """Split pasted Japanese text into pseudo-segments.

        This is useful when the user already has a transcript or when YouTube
        subtitles are unavailable.
        """
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            raise ValueError("Please paste some Japanese text first.")

        raw_chunks = re.split(r"\n{2,}|(?<=[。！？])\s*", normalized)
        segments: list[dict[str, object]] = []
        for chunk in raw_chunks:
            chunk = self._clean_segment_text(chunk)
            if not chunk:
                continue
            if not contains_japanese(chunk):
                continue
            segments.append(
                {
                    "segment_index": len(segments),
                    "start_sec": 0.0,
                    "duration_sec": 0.0,
                    "japanese_text": chunk,
                }
            )
            if len(segments) >= self.max_segments:
                break

        if not segments:
            raise RuntimeError(
                "No usable Japanese segments were found in the pasted text. "
                "Please check the input."
            )

        return segments

    @staticmethod
    def _fetch_transcript_items(video_id: str) -> list[object]:
        """Fetch transcript items across old and new youtube-transcript-api versions."""
        try:
            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id, languages=["ja", "ja-JP"])
            if hasattr(fetched, "to_raw_data"):
                return list(fetched.to_raw_data())
            return list(fetched)
        except AttributeError:
            return list(YouTubeTranscriptApi.get_transcript(video_id, languages=["ja", "ja-JP"]))

    @staticmethod
    def _item_value(item: object, key: str, default: object) -> object:
        """Read a transcript field from either dict items or snippet objects."""
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    @staticmethod
    def _clean_segment_text(text: str) -> str:
        """Normalize a transcript fragment into a cleaner study segment."""
        text = text.replace("\n", " ")
        text = re.sub(r"\[[^\]]+\]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
