from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.config import AppConfig
from src.db import Database
from src.services.article_service import ArticleService
from src.services.furigana_service import FuriganaService
from src.services.transcript_service import TranscriptService
from src.services.vocab_service import VocabService
from src.services.llm_service import LLMService

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

app = FastAPI(title="Japanese Study App")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

config = None
db = Database(config.db_path)
furigana_service = None

def build_article_service(api_key: str, base_url: str, model: str) -> tuple[ArticleService, TranscriptService]:
    llm_service = LLMService(api_key=api_key, base_url=base_url, model=model)
    article_service = ArticleService()
    transcription_service = TranscriptService()
    return article_service, transcription_service

@app.post("/api/article/{article_id}/delete")
def api_delete_article(article_id: int) -> dict[str, Any]:
    db.delete_article(article_id)
    return {"ok": True}