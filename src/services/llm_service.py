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
            return f"{url}/v1"
        return url

    def translate_segments(self, segments: list[str], target_language: str = "English") -> list[str]:

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

