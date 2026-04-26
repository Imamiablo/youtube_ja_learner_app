"""Vocabulary extraction logic."""

import re
from collections import OrderedDict

from src.services.furigana_service import FuriganaService
from src.utils.japanese import contains_japanese, contains_kanji, is_all_katakana


class VocabService:
    """Extract candidate vocabulary directly from transcript text."""

    CONTENT_POS = {"名詞", "動詞", "形容詞", "副詞", "連体詞", "形状詞"}
    SKIP_SURFACES = {
        "する",
        "ある",
        "いる",
        "こと",
        "もの",
        "それ",
        "これ",
        "あれ",
    }
    GENERIC_WORDS = {
        "言う",
        "いう",
        "行く",
        "いく",
        "来る",
        "くる",
        "なる",
        "できる",
        "見る",
        "思う",
        "使う",
        "作る",
        "見る",
        "やる",
        "ある",
        "いる",
        "する",
    }
    QUOTED_TERM_RE = re.compile(r'[「『](.{2,20}?)[」』]')

    def __init__(self, furigana_service: FuriganaService) -> None:
        self.furigana_service = furigana_service

    def extract_vocab(
        self,
        segments: list[dict[str, object]],
        article_title: str = "",
    ) -> list[dict[str, object]]:
        """Build a de-duplicated vocabulary list from transcript segments.

        This intentionally favors deterministic extraction over cleverness.
        Only tokens directly found in the source transcript are included.
        """
        by_key: OrderedDict[str, dict[str, object]] = OrderedDict()
        title_signals = self._build_title_signals(article_title)

        for segment in segments:
            text = str(segment.get("japanese_text", ""))
            segment_id = segment.get("db_segment_id")

            for quoted in self._extract_quoted_terms(text):
                term = quoted["text"]
                unique_key = self._unique_key(display_form=term, orth_base=term, base_form=term)
                if unique_key not in by_key:
                    by_key[unique_key] = {
                        "surface_form": term,
                        "display_form": term,
                        "base_form": term,
                        "orth_base": term,
                        "reading_hiragana": self._reading_for_phrase(term),
                        "pos": "名詞",
                        "pos_detail_1": "引用語",
                        "pos_detail_2": "",
                        "source_segment_id": segment_id,
                        "occurrence_count": 1,
                        "word_type": "technical",
                        "topic_score": 4.5,
                        "source_line_text": text,
                    }
                else:
                    by_key[unique_key]["occurrence_count"] += 1
                    by_key[unique_key]["topic_score"] = max(float(by_key[unique_key].get("topic_score", 0)), 4.5)

            for token in self.furigana_service.token_details(text):
                surface = str(token["surface"]).strip()
                base_form = str(token["base_form"]).strip()
                orth_base = str(token.get("orth_base", "") or "").strip()
                display_form = str(token.get("display_form", "") or surface).strip()
                pos = str(token.get("pos", "") or "").strip()
                pos_detail_1 = str(token.get("pos_detail_1", "") or "").strip()
                pos_detail_2 = str(token.get("pos_detail_2", "") or "").strip()
                is_proper_noun = bool(token.get("is_proper_noun"))
                is_quoted_term = self._is_quoted_term(surface, text)

                if not surface or not base_form:
                    continue
                if not contains_japanese(surface):
                    continue
                if pos and pos not in self.CONTENT_POS:
                    continue
                if len(surface) <= 1 and pos != "名詞":
                    continue
                if base_form in self.SKIP_SURFACES or display_form in self.SKIP_SURFACES:
                    continue

                unique_key = self._unique_key(display_form=display_form, orth_base=orth_base, base_form=base_form)
                if unique_key not in by_key:
                    by_key[unique_key] = {
                        "surface_form": surface,
                        "display_form": display_form,
                        "base_form": base_form,
                        "orth_base": orth_base,
                        "reading_hiragana": token["reading_hiragana"],
                        "pos": pos,
                        "pos_detail_1": pos_detail_1,
                        "pos_detail_2": pos_detail_2,
                        "source_segment_id": segment_id,
                        "occurrence_count": 1,
                        "word_type": "technical" if is_quoted_term else ("name" if is_proper_noun else ""),
                        "topic_score": 0.0,
                        "source_line_text": text,
                    }
                else:
                    by_key[unique_key]["occurrence_count"] += 1

        vocab_items = list(by_key.values())
        for item in vocab_items:
            item["topic_score"] = self._compute_topic_score(item, title_signals)
            if item.get("word_type") not in {"name", "technical"}:
                item["word_type"] = self._infer_word_type(item)

        vocab_items.sort(
            key=lambda item: (
                -float(item.get("topic_score", 0)),
                -int(item.get("occurrence_count", 0)),
                -len(str(item.get("display_form", "") or item.get("surface_form", ""))),
                str(item.get("display_form", "")),
            )
        )
        return vocab_items

    @staticmethod
    def _unique_key(*, display_form: str, orth_base: str, base_form: str) -> str:
        for candidate in (display_form, orth_base, base_form):
            if candidate and contains_japanese(candidate):
                return candidate
        return base_form or display_form or orth_base

    @classmethod
    def _extract_quoted_terms(cls, source_text: str) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for match in cls.QUOTED_TERM_RE.finditer(source_text or ""):
            term = (match.group(1) or "").strip()
            if term and contains_japanese(term):
                items.append({"text": term})
        return items

    @staticmethod
    def _is_quoted_term(surface: str, source_text: str) -> bool:
        if not (is_all_katakana(surface) or contains_japanese(surface)):
            return False
        patterns = [
            f"「{surface}」",
            f"『{surface}』",
            f'"{surface}"',
            f"“{surface}”",
            f"（{surface}）",
            f"({surface})",
        ]
        return any(pattern in source_text for pattern in patterns)

    def _build_title_signals(self, article_title: str) -> dict[str, set[str]]:
        if not article_title.strip():
            return {"forms": set(), "kanji": set()}

        forms: set[str] = set()
        kanji: set[str] = {char for char in article_title if contains_kanji(char)}
        for token in self.furigana_service.token_details(article_title):
            pos = str(token.get("pos", "") or "")
            if pos and pos not in self.CONTENT_POS:
                continue
            for candidate in (
                str(token.get("display_form", "") or ""),
                str(token.get("orth_base", "") or ""),
                str(token.get("base_form", "") or ""),
            ):
                if candidate and contains_japanese(candidate):
                    forms.add(candidate)
                    kanji.update(char for char in candidate if contains_kanji(char))
        return {"forms": forms, "kanji": kanji}

    def _compute_topic_score(self, item: dict[str, object], title_signals: dict[str, set[str]]) -> float:
        score = float(item.get("occurrence_count", 1))
        display_form = str(item.get("display_form", "") or "")
        base_form = str(item.get("base_form", "") or "")
        orth_base = str(item.get("orth_base", "") or "")
        pos = str(item.get("pos", "") or "")

        forms = title_signals.get("forms", set())
        kanji = title_signals.get("kanji", set())

        if display_form in forms or orth_base in forms or base_form in forms:
            score += 4.0

        if kanji:
            overlap = {char for char in display_form if contains_kanji(char) and char in kanji}
            score += float(len(overlap)) * 2.5

        if pos == "名詞":
            score += 1.0
        if self._looks_generic(item):
            score -= 3.0
        if item.get("word_type") == "name":
            score -= 1.0
        if item.get("word_type") == "technical":
            score += 2.5
        if len(display_form) >= 3:
            score += 0.5
        return max(score, 0.0)

    def _infer_word_type(self, item: dict[str, object]) -> str:
        if self._looks_generic(item):
            return "common"

        if (
            int(item.get("occurrence_count", 0)) >= 2
            and float(item.get("topic_score", 0)) >= 3.5
            and str(item.get("pos", "")) in {"名詞", "動詞", "形容詞", "形状詞"}
        ):
            return "technical"

        return "common"

    def _looks_generic(self, item: dict[str, object]) -> bool:
        for candidate in (
            str(item.get("display_form", "") or ""),
            str(item.get("orth_base", "") or ""),
            str(item.get("base_form", "") or ""),
        ):
            if candidate in self.GENERIC_WORDS:
                return True
        return False

    def _reading_for_phrase(self, text: str) -> str:
        parts: list[str] = []
        for token in self.furigana_service.token_details(text):
            reading = str(token.get("reading_hiragana", "") or "").strip()
            surface = str(token.get("surface", "") or "").strip()
            parts.append(reading or surface)
        return "".join(parts)
