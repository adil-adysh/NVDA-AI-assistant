# -*- coding: utf-8 -*-
"""Dependency-free Gemini Developer API client."""

from __future__ import annotations

import json
import os
import ssl
import time
from typing import Any, Dict, Generator, List, Optional, Union
from urllib import error as urllib_error
from urllib import request as urllib_request

from .errors import GeminiAPIError, GeminiClientError
from .types import (
    Content,
    GenerateContentConfig,
    GenerateContentResponse,
    Part,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0


ContentInput = Union[str, Part, Content, Dict[str, Any]]
ContentList = Union[ContentInput, List[ContentInput]]


def _validate_content(content: Content) -> bool:
    if not content.parts:
        return False
    for part in content.parts:
        if part.text or part.data:
            return True
    return False


def _validate_response(response: GenerateContentResponse) -> bool:
    if not response.candidates:
        return False
    if not response.candidates[0].content:
        return False
    return _validate_content(response.candidates[0].content)


def _extract_curated_history(history: list[Content]) -> list[Content]:
    curated_history: list[Content] = []
    i = 0
    while i < len(history):
        current = history[i]
        if current.role not in ["user", "model"]:
            raise ValueError(
                f"Role must be user or model, but got {current.role}"
            )

        if current.role == "user":
            curated_history.append(current)
            i += 1
            continue

        model_output: list[Content] = []
        is_valid = True
        while i < len(history) and history[i].role == "model":
            model_output.append(history[i])
            if not _validate_content(history[i]):
                is_valid = False
            i += 1

        if is_valid:
            curated_history.extend(model_output)
        elif curated_history:
            curated_history.pop()

    return curated_history


def _part_from_input(item: ContentInput) -> Part:
    if isinstance(item, Part):
        return item
    if isinstance(item, str):
        return Part(text=item)
    if isinstance(item, dict):
        return Part.from_dict(item)
    if isinstance(item, Content):
        if len(item.parts) != 1:
            raise GeminiClientError(
                "Content input must contain exactly one part when used as a message part."
            )
        return item.parts[0]
    raise GeminiClientError(
        f"Unsupported message part type: {type(item).__name__}"
    )


def _content_from_input(item: ContentInput) -> Content:
    if isinstance(item, Content):
        return item
    if isinstance(item, Part):
        return Content(parts=[item])
    if isinstance(item, str):
        return Content.from_text(item)
    if isinstance(item, dict):
        dict_content = Content.from_dict(item)
        if dict_content.parts:
            return dict_content
        return Content(parts=[Part.from_dict(item)])
    raise GeminiClientError(
        f"Unsupported content type: {type(item).__name__}"
    )


def _content_from_message(message: Union[ContentInput, List[ContentInput]]) -> Content:
    if isinstance(message, list):
        parts = [_part_from_input(item) for item in message]
        return Content(parts=parts)
    return _content_from_input(message)


class GeminiClient:
    """Minimal Gemini client without third-party dependencies."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        api_token: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.api_token = api_token
        if not self.api_key and not self.api_token:
            raise GeminiClientError(
                "Gemini API key or bearer token is required."
                " Set GEMINI_API_KEY or GOOGLE_API_KEY, or pass api_token."
            )

        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._ssl_context = ssl.create_default_context()
        self.chats = Chats(self)

    def _build_headers(self, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "nvda-gemini-client/1.0",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        else:
            headers["x-goog-api-key"] = self.api_key or ""
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _build_request(
        self,
        path: str,
        body: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> urllib_request.Request:
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(body).encode("utf-8")
        request = urllib_request.Request(url, data=data, method="POST")
        for key, value in self._build_headers(extra_headers).items():
            request.add_header(key, value)
        return request

    def _request_json(self, request: urllib_request.Request) -> Dict[str, Any]:
        attempt = 0
        while True:
            try:
                with urllib_request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                    context=self._ssl_context,
                ) as response:
                    payload = response.read().decode("utf-8")
                    if not payload:
                        return {}
                    return json.loads(payload)
            except urllib_error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                error_payload = None
                try:
                    error_payload = json.loads(body)
                except ValueError:
                    pass
                raise GeminiAPIError(
                    status_code=exc.code,
                    body=body,
                    error=error_payload,
                )
            except urllib_error.URLError as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise GeminiClientError(
                        f"Gemini request failed after {attempt} attempts: {exc}"
                    )
                time.sleep(self.retry_backoff_seconds * attempt)

    def _normalize_contents(self, contents: ContentList) -> List[Dict[str, Any]]:
        if isinstance(contents, list):
            items = contents
        else:
            items = [contents]

        normalized: List[Dict[str, Any]] = []
        for item in items:
            if isinstance(item, Content):
                normalized.append(item.to_dict())
            elif isinstance(item, Part):
                normalized.append(Content(parts=[item]).to_dict())
            elif isinstance(item, str):
                normalized.append(Content.from_text(item).to_dict())
            elif isinstance(item, dict):
                normalized.append(item)
            else:
                raise GeminiClientError(
                    f"Unsupported content type: {type(item).__name__}"
                )

        if not normalized:
            raise GeminiClientError("At least one `contents` item is required.")
        return normalized

    def generate_content(
        self,
        model: str,
        contents: ContentList,
        config: Optional[GenerateContentConfig] = None,
    ) -> GenerateContentResponse:
        """Generate text using a Gemini model."""
        if not model or not model.strip():
            raise GeminiClientError("Model name is required.")

        body: Dict[str, Any] = {
            "model": model,
            "contents": self._normalize_contents(contents),
        }
        if config is not None:
            generation_config = config.to_dict()
            if generation_config:
                body["generationConfig"] = generation_config

        response = self._request_json(
            self._build_request(f"models/{model}:generateContent", body)
        )
        return GenerateContentResponse.from_dict(response)

    def describe_image(
        self,
        model: str,
        image_bytes: bytes,
        prompt: str,
        mime_type: str = "image/png",
        config: Optional[GenerateContentConfig] = None,
    ) -> GenerateContentResponse:
        """Send an image plus a prompt to Gemini and return the text response."""
        if not model or not model.strip():
            raise GeminiClientError("Model name is required.")
        if not image_bytes:
            raise GeminiClientError("image_bytes is required.")
        if not prompt or not prompt.strip():
            raise GeminiClientError("prompt is required.")

        image_part = Part.from_bytes(image_bytes=image_bytes, mime_type=mime_type)
        contents = [
            Content(parts=[image_part]),
            Content.from_text(prompt),
        ]
        return self.generate_content(model=model, contents=contents, config=config)

    def stream_content(
        self,
        model: str,
        contents: ContentList,
        config: Optional[GenerateContentConfig] = None,
    ) -> Generator[str, None, None]:
        """Stream partial Gemini response text using SSE."""
        if not model or not model.strip():
            raise GeminiClientError("Model name is required.")

        body: Dict[str, Any] = {
            "model": model,
            "contents": self._normalize_contents(contents),
        }
        if config is not None:
            generation_config = config.to_dict()
            if generation_config:
                body["generationConfig"] = generation_config

        request = self._build_request(
            f"models/{model}:generateContent?alt=sse",
            body,
            extra_headers={"Accept": "text/event-stream"},
        )

        try:
            with urllib_request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self._ssl_context,
            ) as response:
                yield from self._parse_sse(response)
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            error_payload = None
            try:
                error_payload = json.loads(body)
            except ValueError:
                pass
            raise GeminiAPIError(
                status_code=exc.code,
                body=body,
                error=error_payload,
            )

    def _parse_sse(self, response: Any) -> Generator[str, None, None]:
        buffer = ""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace")
            if not line:
                continue
            stripped = line.strip("\r\n")
            if stripped == "":
                if buffer:
                    yield from self._dispatch_sse_event(buffer)
                    buffer = ""
                continue
            buffer += stripped + "\n"
        if buffer:
            yield from self._dispatch_sse_event(buffer)

    def _dispatch_sse_event(self, event_text: str) -> Generator[str, None, None]:
        data_lines: List[str] = []
        for line in event_text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if not data_lines:
            return

        data = "\n".join(data_lines)
        if data == "[DONE]":
            return

        payload: Dict[str, Any]
        try:
            payload = json.loads(data)
        except ValueError:
            return

        response = GenerateContentResponse.from_dict(payload)
        if response.text:
            yield response.text

class ChatSession:
    """A lightweight Gemini chat session."""

    def __init__(
        self,
        client: "GeminiClient",
        model: str,
        config: Optional[GenerateContentConfig] = None,
        history: Optional[list[Content]] = None,
    ) -> None:
        self._client = client
        self._model = model
        self._config = config
        self._comprehensive_history = history or []
        self._curated_history = _extract_curated_history(self._comprehensive_history)

    def _record_history(
        self,
        user_input: Content,
        model_output: list[Content],
        is_valid: bool,
    ) -> None:
        output_contents = model_output or [Content(role="model", parts=[])]
        self._comprehensive_history.append(user_input)
        self._comprehensive_history.extend(output_contents)
        if is_valid:
            self._curated_history.append(user_input)
            self._curated_history.extend(output_contents)
        elif self._curated_history:
            self._curated_history.pop()

    def get_history(self, curated: bool = False) -> list[Content]:
        return self._curated_history if curated else self._comprehensive_history

    def send_message(
        self,
        message: Union[ContentInput, List[ContentInput]],
        config: Optional[GenerateContentConfig] = None,
    ) -> GenerateContentResponse:
        input_content = _content_from_message(message)
        response = self._client.generate_content(
            model=self._model,
            contents=self._curated_history + [input_content],
            config=config if config else self._config,
        )
        model_output = (
            [response.candidates[0].content]
            if response.candidates and response.candidates[0].content
            else []
        )
        self._record_history(
            user_input=input_content,
            model_output=model_output,
            is_valid=_validate_response(response),
        )
        return response

    def send_message_stream(
        self,
        message: Union[ContentInput, List[ContentInput]],
        config: Optional[GenerateContentConfig] = None,
    ) -> Generator[GenerateContentResponse, None, None]:
        input_content = _content_from_message(message)
        output_contents: list[Content] = []
        is_valid = True
        last_chunk: Optional[GenerateContentResponse] = None
        for chunk in self._client.stream_content(
            model=self._model,
            contents=self._curated_history + [input_content],
            config=config if config else self._config,
        ):
            if not _validate_response(chunk):
                is_valid = False
            if chunk.candidates and chunk.candidates[0].content:
                output_contents.append(chunk.candidates[0].content)
            last_chunk = chunk
            yield chunk

        self._record_history(
            user_input=input_content,
            model_output=output_contents,
            is_valid=is_valid,
        )


class Chats:
    """Utility for creating chat sessions."""

    def __init__(self, client: "GeminiClient") -> None:
        self._client = client

    def create(
        self,
        model: str,
        config: Optional[GenerateContentConfig] = None,
        history: Optional[list[Content]] = None,
    ) -> ChatSession:
        return ChatSession(
            client=self._client,
            model=model,
            config=config,
            history=history,
        )
