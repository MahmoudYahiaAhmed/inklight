"""Optional stronger model behind an OpenAI-compatible chat API.

Disabled unless ``models.remote_base_url`` and ``models.remote_model`` are set.
Only the user's request and a bounded evidence excerpt are ever sent.
"""

from __future__ import annotations

import os
from typing import Any

from ..config import ModelSettings
from ..errors import ModelUnavailable


class RemoteModel:
    def __init__(self, settings: ModelSettings, timeout: float = 60.0) -> None:
        if not (settings.remote_base_url and settings.remote_model):
            raise ModelUnavailable("Remote model is not configured")
        self.base_url = settings.remote_base_url.rstrip("/")
        local = self.base_url.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]"))
        if not self.base_url.startswith("https://") and not local:
            raise ModelUnavailable("Remote model URL must use https:// (plain http is only allowed for localhost)")
        self.model = settings.remote_model
        self.api_key = os.environ.get(settings.remote_api_key_env, "")
        self.timeout = timeout
        self.name = f"remote:{self.model}"

    def chat(self, system: str, user: str, max_tokens: int = 512, json_mode: bool = False) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise ModelUnavailable("Install the remote extra: pip install 'inklight[remote]'") from exc
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"]).strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            # Never echo the key; status and type are enough to debug.
            raise ModelUnavailable(f"Remote model call failed: {type(exc).__name__}") from exc
