from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any


ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["tool", "final"]},
        "tool": {"type": "string", "enum": ["list", "read", "search", "edit"]},
        "arguments": {"type": "object", "properties": {
            "path": {"type": "string"}, "query": {"type": "string"}, "content": {"type": "string"},
        }},
        "response": {"type": "string"},
    },
    "required": ["type"],
}


class ModelClient:
    """Minimal non-streaming Ollama chat adapter."""

    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "qwen2.5-coder:7b", *, timeout_seconds: float = 60):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Ollama endpoint must use a local loopback address.")
        if not model or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama model or endpoint configuration is invalid.")
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def request(self, messages: list[dict[str, str]]) -> str:
        body = json.dumps({"model": self.model, "messages": messages, "stream": False, "format": ACTION_SCHEMA}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read(2 * 1024 * 1024 + 1).decode("utf-8"))
        except (OSError, urllib.error.URLError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Ollama request failed: {error}") from error
        except Exception as error:
            if error.__class__.__name__ == "HTTPError":
                raise RuntimeError(f"Ollama request failed: HTTP {error.code}") from error
            raise
        if not isinstance(payload, dict) or not isinstance(payload.get("message"), dict) or not isinstance(payload["message"].get("content"), str):
            raise RuntimeError("Ollama returned an invalid chat response.")
        return payload["message"]["content"]
