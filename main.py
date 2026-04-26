from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.config import AppConfig
from src.db import Database
from src.services.article_service import ArticleService
from src.services.furigana_service import FuriganaService
from src.services.llm_service import LLMService
from src.services.transcript_service import TranscriptService
from src.services.vocab_service import VocabService

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

app = FastAPI(title="Japanese Study App")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

config = AppConfig()
db = Database(config.db_path)
furigana_service = FuriganaService()


class RatingPayload(BaseModel):
    rating: str


class IgnorePayload(BaseModel):
    ignored: bool


class ContextGlossPayload(BaseModel):
    article_id: int
    segment_id: int
    vocab_item_ids: list[int]
    current_line: str
    previous_line: str = ""
    next_line: str = ""
    article_title: str = ""
    target_language: str = "English"
    api_key: str = ""
    base_url: str = ""
    model: str = ""


def build_article_service(api_key: str, base_url: str, model: str) -> tuple[ArticleService, TranscriptService]:
    llm_service = LLMService(api_key=api_key, base_url=base_url, model=model)
    vocab_service = VocabService(furigana_service)
    article_service = ArticleService(
        db=db,
        furigana_service=furigana_service,
        llm_service=llm_service,
        vocab_service=vocab_service,
    )
    transcript_service = TranscriptService(max_segments=config.max_segments_per_import)
    return article_service, transcript_service


@app.get("/", response_class=HTMLResponse)
def home(request: Request, created: int | None = None, error: str | None = None) -> HTMLResponse:
    articles = db.list_articles()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "articles": articles,
            "created": created,
            "error": error,
            "config": config,
        },
    )


@app.post("/generate")
def generate_article(
    request: Request,
    source_mode: str = Form("youtube"),
    youtube_url: str = Form(""),
    manual_transcript: str = Form(""),
    article_title: str = Form(""),
    target_language: str = Form("English"),
    api_key: str = Form(""),
    base_url: str = Form(""),
    model: str = Form(""),
):
    article_service, transcript_service = build_article_service(api_key, base_url, model)
    try:
        if source_mode == "manual":
            raw_segments = transcript_service.build_segments_from_manual_text(manual_transcript)
            source_type = "manual"
            source_value = manual_transcript[:500]
            title = article_title.strip() or "Manual study article"
        else:
            url = youtube_url.strip()
            if not url:
                raise ValueError("Please provide a YouTube URL.")
            raw_segments = transcript_service.fetch_youtube_segments(url)
            source_type = "youtube"
            source_value = url
            title = article_title.strip() or transcript_service.fetch_youtube_title(url)
        article_id = article_service.create_article(
            title=title,
            source_type=source_type,
            source_value=source_value,
            raw_segments=raw_segments,
            target_language=target_language,
        )
    except Exception as exc:
        return RedirectResponse(url=f"/?error={str(exc)}", status_code=303)

    redirect = RedirectResponse(url=f"/article/{article_id}", status_code=303)
    redirect.set_cookie("jp_last_base_url", base_url, max_age=60 * 60 * 24 * 365)
    redirect.set_cookie("jp_last_model", model, max_age=60 * 60 * 24 * 365)
    redirect.set_cookie("jp_last_target_language", target_language, max_age=60 * 60 * 24 * 365)
    return redirect


@app.get("/article/{article_id}", response_class=HTMLResponse)
def article_page(request: Request, article_id: int) -> HTMLResponse:
    article = db.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    video_id = ""
    if article.get("source_type") == "youtube":
        try:
            video_id = TranscriptService().extract_video_id(str(article.get("source_value", "")))
        except Exception:
            video_id = ""
    return templates.TemplateResponse(
        request,
        "article.html",
        {
            "article": article,
            "video_id": video_id,
            "default_base_url": request.cookies.get("jp_last_base_url", "http://localhost:11434/"),
            "default_model": request.cookies.get("jp_last_model", "qwen3-coder:30b"),
            "default_target_language": request.cookies.get("jp_last_target_language", article.get("notes", {}).get("target_language", "English")),
        },
    )


@app.get("/api/article/{article_id}")
def api_article(article_id: int) -> JSONResponse:
    article = db.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    vocab_by_id = {int(item["id"]): _compact_vocab(item) for item in article["vocab"]}
    segment_vocab_map: dict[str, list[dict[str, Any]]] = {}
    enriched_segments: list[dict[str, Any]] = []

    for segment in article["segments"]:
        seg_id = int(segment["id"])
        candidates = _build_segment_candidates(segment, article["vocab"])
        inline_units = _build_inline_units(str(segment.get("japanese_text", "")), candidates)
        used_ids: list[int] = []
        for unit in inline_units:
            vid = unit.get("vocab_id")
            if isinstance(vid, int) and vid not in used_ids:
                used_ids.append(vid)
        sidebar_ids = used_ids[:]
        for item in candidates:
            item_id = int(item["id"])
            if item_id not in sidebar_ids and len(sidebar_ids) < 12:
                sidebar_ids.append(item_id)
        segment_vocab_map[str(seg_id)] = [vocab_by_id[item_id] for item_id in sidebar_ids if item_id in vocab_by_id]
        enriched_segments.append({
            **segment,
            "end_sec": float(segment.get("start_sec", 0)) + float(segment.get("duration_sec", 0) or 0),
            "inline_units": inline_units,
        })

    payload = {
        "id": article["id"],
        "title": article["title"],
        "source_type": article["source_type"],
        "source_value": article["source_value"],
        "created_at": article["created_at"],
        "notes": article.get("notes", {}),
        "video_id": _safe_video_id(str(article.get("source_value", ""))),
        "segments": enriched_segments,
        "segment_vocab_map": segment_vocab_map,
        "vocab_by_id": vocab_by_id,
    }
    return JSONResponse(payload)


@app.post("/api/vocab/{vocab_item_id}/rate")
def api_rate_vocab(vocab_item_id: int, payload: RatingPayload) -> dict[str, Any]:
    db.set_vocab_rating(vocab_item_id, payload.rating)
    return {"ok": True}


@app.post("/api/vocab/{vocab_item_id}/ignore")
def api_ignore_vocab(vocab_item_id: int, payload: IgnorePayload) -> dict[str, Any]:
    db.set_vocab_ignored(vocab_item_id, payload.ignored)
    return {"ok": True}


@app.post("/api/article/{article_id}/delete")
def api_delete_article(article_id: int) -> dict[str, Any]:
    db.delete_article(article_id)
    return {"ok": True}


@app.post("/api/context-gloss")
def api_context_gloss(payload: ContextGlossPayload) -> dict[str, Any]:
    article = db.get_article(payload.article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    vocab_index = {int(item["id"]): item for item in article["vocab"]}
    vocab_entries = [vocab_index[item_id] for item_id in payload.vocab_item_ids if item_id in vocab_index]
    if not vocab_entries:
        return {"items": []}

    llm = LLMService(api_key=payload.api_key, base_url=payload.base_url, model=payload.model, timeout=60)
    if not llm.enabled:
        return {"items": []}

    prompt_line = payload.current_line
    if payload.previous_line.strip() or payload.next_line.strip():
        prompt_line = f"Previous line: {payload.previous_line}\nCurrent line: {payload.current_line}\nNext line: {payload.next_line}"

    annotations = llm.contextualize_segment_vocab(
        article_title=payload.article_title,
        segment_text=prompt_line,
        vocab_entries=vocab_entries,
        target_language=payload.target_language,
    )
    items = []
    for vocab, ann in zip(vocab_entries, annotations):
        items.append({
            "id": vocab["id"],
            "context_translation": ann.get("context_translation", ""),
            "context_note": ann.get("context_note", ""),
        })
    return {"items": items}


def _safe_video_id(source_value: str) -> str:
    try:
        return TranscriptService().extract_video_id(source_value)
    except Exception:
        return ""


def _compact_vocab(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(item["id"]),
        "surface_form": str(item.get("surface_form", "") or ""),
        "display_form": str(item.get("display_form", "") or ""),
        "base_form": str(item.get("base_form", "") or ""),
        "orth_base": str(item.get("orth_base", "") or ""),
        "reading_hiragana": str(item.get("reading_hiragana", "") or ""),
        "pos": str(item.get("pos", "") or ""),
        "word_type": str(item.get("word_type", "") or "common"),
        "translation_text": str(item.get("translation_text", "") or ""),
        "jlpt_level_estimate": str(item.get("jlpt_level_estimate", "") or ""),
        "occurrence_count": int(item.get("occurrence_count", 0) or 0),
        "topic_score": float(item.get("topic_score", 0) or 0),
        "rating": str(item.get("rating", "") or ""),
        "ignored_in_reviews": int(item.get("ignored_in_reviews", 0) or 0),
    }


def _candidate_text(item: dict[str, Any]) -> str:
    for key in ("display_form", "surface_form", "orth_base", "base_form"):
        text = str(item.get(key, "") or "").strip()
        if text:
            return text
    return ""


def _candidate_priority(item: dict[str, Any]) -> int:
    word_type = str(item.get("word_type", "") or "common")
    base = 0
    if word_type == "technical":
        base += 200
    elif word_type == "name":
        base += 120
    else:
        base += 80
    if str(item.get("jlpt_level_estimate", "")).upper() == "TECHNICAL":
        base += 50
    return base + int(float(item.get("topic_score", 0) or 0) * 10)


def _filter_covered_candidates(segment_text: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    covered_spans: list[tuple[int, int]] = []
    for item in items:
        text = _candidate_text(item)
        idx = segment_text.find(text)
        if idx == -1:
            kept.append(item)
            continue
        span = (idx, idx + len(text))
        is_short = len(text) <= 1
        covered_by_bigger = any(span[0] >= a and span[1] <= b and (b - a) > (span[1] - span[0]) for a, b in covered_spans)
        if covered_by_bigger and (is_short or item.get("word_type") == "common"):
            continue
        kept.append(item)
        covered_spans.append(span)
    return kept


def _build_segment_candidates(segment: dict[str, Any], vocab: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segment_text = str(segment.get("japanese_text", ""))
    bucket: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for item in vocab:
        item_id = int(item["id"])
        if item_id in seen_ids:
            continue
        matched = False
        if int(item.get("source_segment_id") or 0) == int(segment["id"]):
            matched = True
        else:
            for candidate_key in ("display_form", "surface_form", "orth_base", "base_form"):
                candidate = str(item.get(candidate_key, "") or "").strip()
                if candidate and candidate in segment_text:
                    matched = True
                    break
        if matched:
            bucket.append(_compact_vocab(item))
            seen_ids.add(item_id)
    bucket.sort(key=lambda item: (-_candidate_priority(item), -len(str(item.get("display_form", "") or item.get("surface_form", ""))), -int(item.get("occurrence_count", 0))))
    return _filter_covered_candidates(segment_text, bucket)


def _build_inline_units(segment_text: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for item in items:
        text = _candidate_text(item)
        if not text:
            continue
        pos = segment_text.find(text)
        while pos != -1:
            candidates.append({"start": pos, "end": pos + len(text), "text": text, "item": item})
            pos = segment_text.find(text, pos + len(text))
    candidates.sort(key=lambda c: (c["start"], -(c["end"] - c["start"])))

    units: list[dict[str, Any]] = []
    idx = 0
    used_until = 0
    for c in candidates:
        if c["start"] < used_until:
            continue
        if idx < c["start"]:
            plain = segment_text[idx:c["start"]]
            units.append({"text": plain, "plain": plain, "html": furigana_service.render_ruby_html(plain) if plain else ""})
        token = c["text"]
        item = c["item"]
        units.append({
            "text": token,
            "plain": token,
            "html": furigana_service.render_ruby_html(token),
            "vocab_id": int(item["id"]),
        })
        idx = c["end"]
        used_until = c["end"]
    if idx < len(segment_text):
        plain = segment_text[idx:]
        units.append({"text": plain, "plain": plain, "html": furigana_service.render_ruby_html(plain) if plain else ""})
    return units
