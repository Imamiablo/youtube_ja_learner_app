"""Generate furigana-ready HTML from Japanese text."""

from fugashi import Tagger

from src.utils.japanese import contains_japanese, contains_kanji, is_all_katakana, katakana_to_hiragana, safe_html


class FuriganaService:
    """Wrap Japanese tokens in HTML ruby tags when readings are available."""

    def __init__(self) -> None:
        self.tagger = Tagger()

    def render_ruby_html(self, text: str) -> str:
        """Return HTML with <ruby> markup for tokens containing kanji."""
        parts: list[str] = []
        for token in self.tagger(text):
            surface = token.surface
            reading = self._extract_reading(token)
            if contains_kanji(surface) and reading:
                parts.append(
                    f"<ruby>{safe_html(surface)}<rt>{safe_html(reading)}</rt></ruby>"
                )
            else:
                parts.append(safe_html(surface))
        return "".join(parts)

    def token_details(self, text: str) -> list[dict[str, str | bool]]:
        """Return detailed token information for vocabulary extraction."""
        details: list[dict[str, str | bool]] = []
        for token in self.tagger(text):
            surface = token.surface.strip()
            if not surface:
                continue
            orth_base = self._extract_orth_base(token) or surface
            details.append(
                {
                    "surface": surface,
                    "base_form": self._extract_lemma(token) or surface,
                    "orth_base": orth_base,
                    "display_form": self._pick_display_form(surface, orth_base, self._extract_lemma(token) or surface),
                    "reading_hiragana": self._extract_reading(token),
                    "pos": self._extract_pos(token),
                    "pos_detail_1": self._extract_pos_detail(token, 1),
                    "pos_detail_2": self._extract_pos_detail(token, 2),
                    "is_proper_noun": self._extract_pos_detail(token, 1) == "固有名詞",
                }
            )
        return details

    @staticmethod
    def _pick_display_form(surface: str, orth_base: str, base_form: str) -> str:
        if is_all_katakana(surface):
            return surface
        for candidate in (orth_base, base_form, surface):
            if candidate and contains_japanese(candidate):
                return candidate
        return surface or base_form or orth_base

    @staticmethod
    def _extract_pos(token: object) -> str:
        """Extract a readable part-of-speech label from a tokenizer token."""
        feature = getattr(token, "feature", None)
        if feature is None:
            return ""

        pos = getattr(feature, "pos1", None)
        if pos:
            return str(pos)

        if isinstance(feature, (tuple, list)) and feature:
            return str(feature[0])

        return ""

    @staticmethod
    def _extract_pos_detail(token: object, detail_index: int) -> str:
        feature = getattr(token, "feature", None)
        if feature is None:
            return ""

        attr_map = {1: "pos2", 2: "pos3", 3: "pos4"}
        attr_name = attr_map.get(detail_index)
        if attr_name:
            value = getattr(feature, attr_name, None)
            if value and value != "*":
                return str(value)

        tuple_index = detail_index
        if isinstance(feature, (tuple, list)) and len(feature) > tuple_index and feature[tuple_index] != "*":
            return str(feature[tuple_index])

        return ""

    @staticmethod
    def _extract_lemma(token: object) -> str:
        """Extract the lemma / dictionary form of a token."""
        feature = getattr(token, "feature", None)
        if feature is None:
            return token.surface

        for attr in ("lemma", "dictionary_form"):
            value = getattr(feature, attr, None)
            if value and value != "*":
                return str(value)

        if isinstance(feature, (tuple, list)) and len(feature) > 6 and feature[6] != "*":
            return str(feature[6])

        return token.surface

    @staticmethod
    def _extract_orth_base(token: object) -> str:
        """Extract the orthographic base form when available."""
        feature = getattr(token, "feature", None)
        if feature is None:
            return token.surface

        for attr in ("orthBase", "orth_base"):
            value = getattr(feature, attr, None)
            if value and value != "*":
                return str(value)

        if isinstance(feature, (tuple, list)) and len(feature) > 10 and feature[10] != "*":
            return str(feature[10])

        return token.surface

    @staticmethod
    def _extract_reading(token: object) -> str:
        """Extract token reading and convert it to hiragana when possible."""
        feature = getattr(token, "feature", None)
        if feature is None:
            return ""

        for attr in ("kana", "pron", "reading", "reading_form"):
            value = getattr(feature, attr, None)
            if value and value != "*":
                return katakana_to_hiragana(str(value))

        if isinstance(feature, (tuple, list)):
            for index in (7, 6):
                if len(feature) > index and feature[index] != "*":
                    return katakana_to_hiragana(str(feature[index]))

        return ""
