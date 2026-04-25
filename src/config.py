import os
from dataclasses import dataclass

@dataclass(slots=True)
class AppConfig:

    db_path: str = os.getenv("APP_BD_PATH", "data/japanese_study.db")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "")
    max_segments_per_import: int = int(os.getenv("MAX_SEGMENTS_PER_IMPORT", "120"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_base_url and self.openai_model)
