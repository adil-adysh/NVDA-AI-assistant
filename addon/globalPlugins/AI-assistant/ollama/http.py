# -*- coding: utf-8 -*-
import json
import socket
import time
from typing import Any, Callable
from urllib import error as urllibError
from urllib import request as urllibRequest

from logHandler import log
from .errors import OllamaClientError


def _parseJSON(raw: str, path: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        snippet = raw[:240].strip().replace("\n", " ")
        if snippet:
            raise OllamaClientError(
                f"Ollama returned invalid JSON for {path}: {error}. Response starts with: {snippet}"
            )
        raise OllamaClientError(f"Ollama returned invalid JSON for {path}: {error}")

    if not isinstance(parsed, dict):
        raise OllamaClientError(f"Ollama returned an unexpected response payload for {path}.")
    return parsed


def _readErrorBody(error: urllibError.HTTPError) -> str:
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
        message = str(parsed.get("error", "")).strip()
        if message:
            return message
    return raw[:500]


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

    request = urllibRequest.Request(
        url=baseURL + path,
        data=body,
        headers=headers,
        method=method,
    )
    lastErrorMessage = ""
    attempts = 3

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            with urllibRequest.urlopen(request, timeout=timeoutSeconds) as response:
                try:
                    raw = response.read().decode("utf-8")
                except UnicodeDecodeError as error:
                    raise OllamaClientError(
                        f"Ollama returned non-UTF-8 content for {path}: {error}"
                    )
                return _parseJSON(raw, path)
        except urllibError.HTTPError as error:
            details = _readErrorBody(error)
            lastErrorMessage = f"HTTP {error.code}. {details}" if details else f"HTTP {error.code}."
            if attempt >= attempts:
                raise OllamaClientError(f"Ollama request failed for {path} after {attempt} attempt(s): {lastErrorMessage}")
        except urllibError.URLError as error:
            reason = getattr(error, "reason", None)
            if isinstance(reason, socket.timeout) or "timed out" in str(reason or "").lower():
                lastErrorMessage = (
                    f"Timed out waiting for response from {baseURL}{path} "
                    f"after {timeoutSeconds:.1f}s (timeout={timeoutSeconds:.1f}s)."
                )
            else:
                lastErrorMessage = (
                    f"Unable to reach Ollama at {baseURL}. Reason: {str(reason or error).strip() or 'unknown network error'}."
                )
            if attempt >= attempts:
                raise OllamaClientError(lastErrorMessage)
        except socket.timeout:
            lastErrorMessage = (
                f"Timed out waiting for response from {baseURL}{path} "
                f"after {timeoutSeconds:.1f}s (timeout={timeoutSeconds:.1f}s)."
            )
            if attempt >= attempts:
                raise OllamaClientError(lastErrorMessage)
        except OSError as error:
            lastErrorMessage = f"Ollama request failed: {error}"
            if attempt >= attempts:
                raise OllamaClientError(lastErrorMessage)

        time.sleep(0.5)


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
