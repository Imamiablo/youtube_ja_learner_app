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

        return article_id