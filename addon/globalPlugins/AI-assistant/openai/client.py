# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import socket
import time
from collections.abc import Generator
from typing import Any
from urllib import error as urllibError
from urllib import request as urllibRequest
from urllib.parse import quote

from logHandler import log

from .errors import OpenAIClientConfigurationError, OpenAIClientError


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com",
        chat_path: str = "/v1/chat/completions",
        timeout_seconds: float = 60.0,
        organization: str | None = None,
    ) -> None:
        self._api_key = str(api_key or "").strip()
        if not self._api_key:
            raise OpenAIClientConfigurationError("OpenAI API key is required.")

        self._base_url = str(base_url or "").rstrip("/")
        if not self._base_url:
            raise OpenAIClientConfigurationError("OpenAI base URL is required.")

        self._chat_path = str(chat_path or "/v1/chat/completions").strip()
        if not self._chat_path.startswith("/"):
            self._chat_path = f"/{self._chat_path}"

        self._timeout_seconds = float(timeout_seconds)
        self._organization = str(organization).strip() if organization else None

    def create_chat_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        top_p: float = 0.85,
        top_k: int | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
        }
        if top_k is not None:
            payload["top_k"] = top_k
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools is not None:
            payload["tools"] = tools

        return self._request_json(self._chat_path, payload)

    def stream_chat_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        top_p: float = 0.85,
        top_k: int | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "stream": True,
        }
        if top_k is not None:
            payload["top_k"] = top_k
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools is not None:
            payload["tools"] = tools

        yield from self._request_sse(self._chat_path, payload)

    def list_models(self) -> dict[str, Any]:
        return self._request_json(self._models_path(), method="GET")

    def get_model(self, model: str) -> dict[str, Any]:
        if not model or not model.strip():
            raise OpenAIClientConfigurationError("OpenAI model name is required.")
        return self._request_json(self._model_path(model.strip()), method="GET")

    def _models_path(self) -> str:
        chat_path = self._chat_path.rstrip("/")
        suffix = "/chat/completions"
        if chat_path.endswith(suffix):
            prefix = chat_path[: -len(suffix)]
            return f"{prefix}/models" if prefix else "/models"
        return "/v1/models"

    def _model_path(self, model: str) -> str:
        encoded_model = quote(model, safe="")
        return f"{self._models_path().rstrip('/')}/{encoded_model}"

    def _build_url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "browser-assistant/0.1",
        }
        if self._organization:
            headers["OpenAI-Organization"] = self._organization
        return headers

    def _parse_json(self, raw: str, path: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            snippet = raw[:240].strip().replace("\n", " ")
            if snippet:
                raise OpenAIClientError(
                    f"OpenAI returned invalid JSON for {path}: {error}. Response starts with: {snippet}"
                )
            raise OpenAIClientError(f"OpenAI returned invalid JSON for {path}: {error}")

        if not isinstance(parsed, dict):
            raise OpenAIClientError(f"OpenAI returned an unexpected payload for {path}.")
        return parsed

    def _read_error_body(self, error: urllibError.HTTPError) -> str:
        try:
            raw = error.read().decode("utf-8").strip()
        except Exception:
            raw = ""
        if not raw:
            return ""

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw[:500]

        if isinstance(parsed, dict):
            error_message = parsed.get("error")
            if isinstance(error_message, dict):
                return str(error_message.get("message", "")) or raw[:500]
            return str(error_message)
        return raw[:500]

    def _parse_sse(self, response: Any) -> Generator[dict[str, Any], None, None]:
        buffer = ""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace")
            if not line:
                continue
            stripped = line.strip("\r\n")
            if stripped == "":
                if buffer:
                    event = self._parse_sse_event(buffer)
                    buffer = ""
                    if event is not None:
                        yield event
                continue
            buffer += stripped + "\n"

        if buffer:
            event = self._parse_sse_event(buffer)
            if event is not None:
                yield event

    def _parse_sse_event(self, event_text: str) -> dict[str, Any] | None:
        data_lines: list[str] = []
        for line in event_text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())

        if not data_lines:
            return None

        data = "\n".join(data_lines)
        if data == "[DONE]":
            return None

        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as error:
            raise OpenAIClientError(f"OpenAI returned invalid SSE JSON: {error}") from error

        if not isinstance(parsed, dict):
            raise OpenAIClientError("OpenAI returned an unexpected SSE payload.")
        return parsed

    def _request_sse(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> Generator[dict[str, Any], None, None]:
        body = json.dumps(payload).encode("utf-8")
        headers = self._build_headers()
        headers["Accept"] = "text/event-stream"

        request = urllibRequest.Request(
            url=self._build_url(path),
            data=body,
            headers=headers,
            method="POST",
        )

        attempts = 3
        last_error_message = ""
        last_status_code: int | None = None

        for attempt in range(1, attempts + 1):
            try:
                with urllibRequest.urlopen(request, timeout=self._timeout_seconds) as response:
                    yield from self._parse_sse(response)
                    return
            except urllibError.HTTPError as error:
                details = self._read_error_body(error)
                code = getattr(error, "code", "?")
                last_status_code = code if isinstance(code, int) else None
                last_error_message = f"HTTP {code}. {details}" if details else f"HTTP {code}."
            except urllibError.URLError as error:
                reason = getattr(error, "reason", None)
                if isinstance(reason, socket.timeout) or "timed out" in str(reason or "").lower():
                    last_error_message = (
                        f"Timed out waiting for streaming response from {self._build_url(path)} "
                        f"after {self._timeout_seconds:.1f}s."
                    )
                else:
                    last_error_message = (
                        f"Unable to reach OpenAI at {self._build_url(path)}. Reason: "
                        f"{str(reason or error).strip() or 'unknown network error'}."
                    )
            except socket.timeout:
                last_error_message = (
                    f"Timed out waiting for streaming response from {self._build_url(path)} "
                    f"after {self._timeout_seconds:.1f}s."
                )
            except OSError as error:
                last_error_message = f"OpenAI streaming request failed: {error}"

            if attempt >= attempts:
                raise OpenAIClientError(
                    f"OpenAI streaming request failed for {path} after {attempt} attempt(s): {last_error_message}",
                    status_code=last_status_code,
                    path=path,
                )

            time.sleep(0.5)

    def _request_json(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        method: str = "POST",
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self._build_headers()

        request = urllibRequest.Request(
            url=self._build_url(path),
            data=body,
            headers=headers,
            method=method,
        )

        attempts = 3
        last_error_message = ""
        last_status_code: int | None = None

        for attempt in range(1, attempts + 1):
            try:
                with urllibRequest.urlopen(request, timeout=self._timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return self._parse_json(raw, path)
            except urllibError.HTTPError as error:
                details = self._read_error_body(error)
                code = getattr(error, "code", "?")
                last_status_code = code if isinstance(code, int) else None
                last_error_message = f"HTTP {code}. {details}" if details else f"HTTP {code}."
            except urllibError.URLError as error:
                reason = getattr(error, "reason", None)
                if isinstance(reason, socket.timeout) or "timed out" in str(reason or "").lower():
                    last_error_message = (
                        f"Timed out waiting for response from {self._build_url(path)} "
                        f"after {self._timeout_seconds:.1f}s."
                    )
                else:
                    last_error_message = (
                        f"Unable to reach OpenAI at {self._build_url(path)}. Reason: "
                        f"{str(reason or error).strip() or 'unknown network error'}."
                    )
            except socket.timeout:
                last_error_message = (
                    f"Timed out waiting for response from {self._build_url(path)} "
                    f"after {self._timeout_seconds:.1f}s."
                )
            except OSError as error:
                last_error_message = f"OpenAI request failed: {error}"

            if attempt >= attempts:
                raise OpenAIClientError(
                    f"OpenAI request failed for {path} after {attempt} attempt(s): {last_error_message}",
                    status_code=last_status_code,
                    path=path,
                )

            time.sleep(0.5)
