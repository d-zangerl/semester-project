from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


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
        _tool_action_schema("check", _argument_schema({"name": {"type": "string"}}, ["name"])),
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


DEFAULT_BASE_URL = "https://lion.aida.cs.technikum-wien.at/v1"
DEFAULT_MODEL = "Qwen/Qwen3.6-35B-A3B"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ModelUnavailableError(RuntimeError):
    """The model service could not answer; the task should pause rather than fail."""


class ModelRejectedError(ModelUnavailableError):
    """The service refused the API key; retrying cannot help."""


class ModelReply(str):
    """The reply text, plus the tokens the request consumed."""

    tokens: int
    tokens_estimated: bool

    def __new__(cls, text: str, tokens: int, tokens_estimated: bool) -> "ModelReply":
        reply = super().__new__(cls, text)
        reply.tokens = tokens
        reply.tokens_estimated = tokens_estimated
        return reply


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


class ModelClient:
    """Minimal non-streaming client for any OpenAI-compatible chat endpoint."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL, *, api_key: str | None = None,
                 timeout_seconds: float = 300, retry_waits: tuple[float, ...] = (5, 15, 45),
                 sleep: Callable[[float], None] = time.sleep):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Model endpoint must be an http or https URL.")
        if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("Non-local model endpoints must use HTTPS.")
        if not model or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Model or endpoint configuration is invalid.")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.retry_waits = retry_waits
        self._sleep = sleep
        self._use_schema = True

    def __repr__(self) -> str:
        return f"ModelClient({self.base_url!r}, {self.model!r})"

    def request(self, messages: list[dict[str, str]]) -> ModelReply:
        waits = iter(self.retry_waits)
        while True:
            try:
                return self._attempt(messages)
            except ModelRejectedError:
                raise
            except ModelUnavailableError:
                wait = next(waits, None)
                if wait is None:
                    raise
                self._sleep(wait)

    def _attempt(self, messages: list[dict[str, str]]) -> ModelReply:
        body = {"model": self.model, "messages": messages, "stream": False}
        if self._use_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "action", "schema": ACTION_SCHEMA}}
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode("utf-8"),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read(2 * 1024 * 1024 + 1).decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise ModelRejectedError(f"Model service rejected the API key (HTTP {error.code}).") from None
            if error.code == 400 and self._use_schema:
                self._use_schema = False
                return self._attempt(messages)
            raise ModelUnavailableError(f"Model request failed: HTTP {error.code}") from None
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ModelUnavailableError(f"Model request failed: {type(error).__name__}") from None
        try:
            text = payload["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
        except (KeyError, IndexError, TypeError):
            raise ModelUnavailableError("Model service returned an invalid chat response.") from None
        usage = payload.get("usage")
        tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        if isinstance(tokens, int) and not isinstance(tokens, bool):
            return ModelReply(text, tokens, False)
        return ModelReply(text, estimate_tokens(json.dumps(messages) + text), True)


def client_from_environment(env_file: str | Path | None = None) -> ModelClient:
    """Build the client from OPENAI_BASE_URL, OPENAI_API_KEY, CODING_HARNESS_MODEL and an optional .env file."""
    from dotenv import load_dotenv

    load_dotenv(env_file or Path(__file__).resolve().parents[2] / ".env")
    return ModelClient(
        os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        os.environ.get("CODING_HARNESS_MODEL", DEFAULT_MODEL),
        api_key=os.environ.get("OPENAI_API_KEY") or None,
        timeout_seconds=float(os.environ.get("CODING_HARNESS_MODEL_TIMEOUT", "300")),
    )
