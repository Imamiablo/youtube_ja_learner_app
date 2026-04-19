from __future__ import annotations

import json
from typing import Any

import requests


class LLMService:

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 90) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url
        self.model = model.strip()
        self.timeout = timeout