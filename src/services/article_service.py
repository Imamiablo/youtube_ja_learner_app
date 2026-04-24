from typing import Any

from src.services.llm_service import LLMService
from src.services.furigana_service import FuriganaService
from src.services.vocab_service import VocabService
from src.db import Database

#from src.services.

class ArticleService:

    def __init__(
            self,
            *,
            db: Database,
            furigana_service: FuriganaService,
            llm_service: LLMService,
            vocab_service: VocabService,

    ) -> None:
        self.db = db
        self.furigana_service = furigana_service
        self.llm_service = llm_service
        self.vocab_service = vocab_service

    def create_article(
            self,
            *,
            title: str,
            source_type: str,
            source_value: str,
            raw_segments: list[dict[str, Any]],
            target_language: str = "English",
    ) -> int:
        article_id = self.db.insert_article(
            title=title,
            source_type=source_type,
            source_value=source_value,
            notes={"target_language": target_language},
        )

        japanese_texts = [str(item.get("japanese_text", "")) for item in raw_segments]
        translations = [""] * len(japanese_texts)
        TRANSLATION_BATCH_SIZE = 12

        if self.llm_service.enabled:
            for start in range(0, len(japanese_texts), TRANSLATION_BATCH_SIZE):
                chunk = japanese_texts[start:start + TRANSLATION_BATCH_SIZE]
                translated_chunk = self.llm_service.translate_segments(chunk, target_language=target_language)
                for offset, value in enumerate(translated_chunk):
                    index = start + offset
                    if index < len(translations):
                        translations[index] = value

        enriched_segments: list[dict[str, Any]] = []
        for idx, japanese_text in enumerate(japanese_texts):
            segment = raw_segments[idx]
            enriched_segments.append({
                "segment_index": int(segment.get("segment_index", idx)),
                "start_sec": float(segment.get("start_sec", 0)),
                "duration_sec": float(segment.get("duration_sec", 0)),
                "japanese_text": translations[idx] if idx < len(translations) else "",
                "furigana_html": self.furigana_service.render_ruby_html(japanese_text),
            })


        return article_id