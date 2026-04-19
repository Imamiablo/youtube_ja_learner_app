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