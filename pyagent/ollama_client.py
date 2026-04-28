import json
import logging
from typing import Any

import requests

from config import load_config

logger = logging.getLogger("pyagent")


class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None):
        cfg = load_config()
        self.host = (host or cfg.ollama_host).rstrip("/")
        self.model = model or cfg.model
        self.temperature = cfg.temperature
        self.max_tokens = cfg.max_tokens

    def _post(self, endpoint: str, data: dict) -> dict:
        url = f"{self.host}{endpoint}"
        logger.debug("POST %s", url)
        r = requests.post(url, json=data, timeout=120, stream=False)
        r.raise_for_status()
        return r.json()

    def list_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=10)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools
        if system:
            payload["system"] = system

        return self._post("/api/chat", payload)

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
    ):
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools
        if system:
            payload["system"] = system

        url = f"{self.host}/api/chat"
        logger.debug("POST (stream) %s", url)
        r = requests.post(url, json=payload, timeout=300, stream=True)
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        if system:
            payload["system"] = system

        data = self._post("/api/generate", payload)
        return data.get("response", "")
