# -*- coding: utf-8 -*-
import json
import socket
from typing import Any, Callable
from urllib import error as urllibError
from urllib import request as urllibRequest

from logHandler import log
from ..providers._http_utils import parse_json_response, read_error_body, request_json_with_retry
from .errors import OllamaClientError


def _parseJSON(raw: str, path: str) -> dict[str, Any]:
    """Parse Ollama JSON response (delegates to shared utility)."""
    try:
        return parse_json_response(raw, path, "Ollama")
    except ValueError as error:
        raise OllamaClientError(str(error)) from error


def _readErrorBody(error: urllibError.HTTPError) -> str:
    """Extract error message from Ollama HTTPError (delegates to shared utility)."""
    return read_error_body(error)


def _requestJSON(
    baseURL: str,
    path: str,
    method: str,
    timeoutSeconds: float,
    requestHeaders: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    headers = dict(requestHeaders)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    def make_request() -> urllibRequest.Request:
        return urllibRequest.Request(
            url=baseURL + path,
            data=body,
            headers=headers,
            method=method,
        )

    try:
        return request_json_with_retry(
            make_request=make_request,
            timeout=timeoutSeconds,
            provider="Ollama",
            path=path,
            attempts=3,
            backoff=0.5,
        )
    except ValueError as error:
        raise OllamaClientError(str(error)) from error


def _requestPullStream(
    baseURL: str,
    path: str,
    timeoutSeconds: float,
    payload: dict[str, Any],
    onProgress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/x-ndjson",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "User-Agent": "browser-assistant/0.1",
    }
    request = urllibRequest.Request(
        url=baseURL + path,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllibRequest.urlopen(request, timeout=timeoutSeconds) as response:
            lastParsed: dict[str, Any] = {}
            while True:
                rawLine = response.readline()
                if not rawLine:
                    break
                try:
                    line = rawLine.decode("utf-8").strip()
                except UnicodeDecodeError as error:
                    raise OllamaClientError(
                        f"Ollama pull stream contained non-UTF-8 content for {path}: {error}"
                    )
                if not line:
                    continue
                parsed = _parseJSON(line, path)
                errorMessage = str(parsed.get("error", "")).strip()
                if errorMessage:
                    raise OllamaClientError(f"Ollama pull failed for {path}: {errorMessage}")
                if onProgress is not None:
                    try:
                        onProgress(parsed)
                    except Exception:
                        log.exception("onProgress callback failed")
                lastParsed = parsed
            return lastParsed
    except urllibError.HTTPError as error:
        details = _readErrorBody(error)
        raise OllamaClientError(f"Ollama request failed for {path}: HTTP {error.code}. {details}")
    except urllibError.URLError as error:
        reason = getattr(error, "reason", None)
        if isinstance(reason, socket.timeout) or "timed out" in str(reason or "").lower():
            raise OllamaClientError(
                f"Timed out waiting for response from {baseURL}{path} "
                f"after {timeoutSeconds:.1f}s (timeout={timeoutSeconds:.1f}s)."
            )
        raise OllamaClientError(
            f"Unable to reach Ollama at {baseURL}. Reason: {str(reason or error).strip() or 'unknown network error'}."
        )
    except socket.timeout:
        raise OllamaClientError(
            f"Timed out waiting for response from {baseURL}{path} "
            f"after {timeoutSeconds:.1f}s (timeout={timeoutSeconds:.1f}s)."
        )
    except OSError as error:
        raise OllamaClientError(f"Ollama request failed: {error}")
