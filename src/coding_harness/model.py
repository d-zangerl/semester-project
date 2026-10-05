from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any


def _tool_action_schema(name: str, arguments: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "type": {"const": "tool"},
            "tool": {"const": name},
            "arguments": arguments,
        },
        "required": ["type", "tool", "arguments"],
        "additionalProperties": False,
    }


def _argument_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


ACTION_SCHEMA = {
    "type": "object",
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "final"},
                "response": {"type": "string"},
            },
            "required": ["type", "response"],
            "additionalProperties": False,
        },
        _tool_action_schema("list", _argument_schema({"path": {"type": "string"}}, [])),
        _tool_action_schema("read", _argument_schema({
            "path": {"type": "string"},
            "start": {"type": "integer"},
            "end": {"type": "integer"},
        }, ["path"])),
        _tool_action_schema("search", _argument_schema({
            "query": {"type": "string"},
            "path": {"type": "string"},
        }, ["query"])),
        _tool_action_schema("edit", {
            "oneOf": [
                _argument_schema({
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                }, ["path", "content"]),
                _argument_schema({
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                }, ["path", "old", "new"]),
                _argument_schema({
                    "path": {"type": "string"},
                    "after_line": {"type": "integer"},
                    "text": {"type": "string"},
                }, ["path", "after_line", "text"]),
                _argument_schema({
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "text": {"type": "string"},
                }, ["path", "start_line", "end_line", "text"]),
                _argument_schema({
                    "path": {"type": "string"},
                    "function": {"type": "string"},
                    "function_content": {"type": "string"},
                }, ["path", "function", "function_content"]),
            ],
        }),
    ],
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
