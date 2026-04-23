from __future__ import annotations

import json
from typing import Any

import requests


class LLMService:

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 90) -> None:
        self.api_key = api_key.strip()
        self.base_url = self._normalize_base_url(base_url)
        self.model = model.strip()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """ Make URL workable both for ollama and openAI"""

        url = base_url.strip().rstrip("/")
        if not url:
            return ""
        if url.endswith("/v1"):
            return url
        if "localhost:11434" in url or "127.0.0.1:11434" in url:
            return f"{url}/v1" # openAI requires this
        return url

    def translate_segments(self, segments: list[str], target_language: str = "English") -> list[str]:
        """
        Accepts list with segments of text to be translated;
        Gives it to LLM to generate translation;
        Returns list with translated segments

        target language: any language model knows
        """
        if not self.enabled or not segments:
            return ("") * len(segments)

        numbered_segments = [{"index": i, "text": text} for i, text in enumerate(segments)]
        system_prompt = (
            "You translate Japanese study material. Return only valid JSON. "
            "Do not invent extra content. Keep each translation faithful, concise, and natural."
        )
        user_prompt = (
            f"Translate the following Japanese segments into {target_language}.\n"
            "Return a JSON array. Each item must look like: "
            '{"index": 0, "translation": "..."}.\n\n'
            f"Segments:\n{json.dumps(numbered_segments, ensure_ascii=False)}"
        )

        raw = self._chat(system_prompt=system_prompt, user_prompt=user_prompt)
        payload = self._parse_json_payload(raw)

        translations = [""] * len(segments)
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                index = item.get("index")
                if isinstance(index, int) and 0 <= index < len(translations):
                    translations[index] = str(item.get("translation", "")).strip()
        return translations

    def annotate_vocab(
            self,
            vocab_entries: list[dict[str, Any]],
            target_language: str = "English",
            article_title: str = "",
    ) -> list[dict[str, str]]:

        if not self.enabled or not vocab_entries:
            return [{"translation_text": "", "jlpt_level_estimate": ""} for _ in vocab_entries]

        annotations = {"translation_text": "", "jlpt_level_estimate": ""}
        return annotations

    def contextualize_segment_vocab(
            self,
            *,
            article_title: str,
            segment_text: str,
            vocab_entries: list[dict[str, Any]],
            target_language: str = "English",
    ) -> list[dict[str, str]]:

        if not self.enabled or not segment_text.strip():
            return [{"context_translation": "", "context_not": ""} for _ in vocab_entries]

        output = {"context_translation": "", "context_note": ""}
        return output

    def _chat(self, *, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise RuntimeError(
                "LLM request Timeout. Try a smaller transcript or check whether your LLM is capable and living"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"LLM request error: {exc}") from exc
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

    @staticmethod
    def _parse_json_payload(raw_text: str) -> Any:
        """ Accepts messy LLM answer and returns parsed JSON data if possible """

        # Accept raw text and check whether it works as is for JSON
        raw_text = raw_text.strip()
        if not raw_text:
            return None
        try:
            return json.loads(raw_text)

        # raw text might contain extra conversation from LLM
        except json.decoder.JSONDecodeError:
            pass
        # find where JSON starts
        start_candidates = [idx for idx in (raw_text.find("["), raw_text.find("{")) if idx != -1]
        if not start_candidates:
            return None
        start = min(start_candidates)
        # find valid JSON structure within raw_text
        for end in range(len(raw_text), start, -1):
            snippet = raw_text[start:end]
            try:
                return json.loads(snippet)
            except json.decoder.JSONDecodeError:
                continue
        # LLM could not produce JSON-containing string
        return None



