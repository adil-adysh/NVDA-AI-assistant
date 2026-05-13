# -*- coding: utf-8 -*-
"""
Shared HTTP utility functions for provider API clients.

Consolidates the nearly identical JSON parsing, error-body reading, and
retry-with-backoff patterns that were duplicated across the Ollama, OpenAI,
and Gemini client implementations.
"""
from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable
from typing import Any
from urllib import error as urllibError
from urllib import request as urllibRequest


def parse_json_response(raw: str, path: str, provider: str = "Provider") -> dict[str, Any]:
	"""Parse a JSON response body with a descriptive error on failure."""
	try:
		parsed = json.loads(raw)
	except json.JSONDecodeError as error:
		snippet = raw[:240].strip().replace("\n", " ")
		if snippet:
			raise ValueError(
				f"{provider} returned invalid JSON for {path}: {error}. "
				f"Response starts with: {snippet}"
			)
		raise ValueError(f"{provider} returned invalid JSON for {path}: {error}")

	if not isinstance(parsed, dict):
		raise ValueError(f"{provider} returned an unexpected response payload for {path}.")
	return parsed


def read_error_body(error: urllibError.HTTPError) -> str:
	"""Extract a human-readable error message from an HTTPError response body."""
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
		error_value = parsed.get("error")
		if isinstance(error_value, dict):
			return str(error_value.get("message", "")) or raw[:500]
		return str(error_value) if error_value else raw[:500]
	return raw[:500]


def request_json_with_retry(
	make_request: Callable[[], urllibRequest.Request],
	timeout: float,
	provider: str,
	path: str,
	*,
	attempts: int = 3,
	backoff: float = 0.5,
) -> dict[str, Any]:
	"""Execute a JSON HTTP request with a retry loop.

	Args:
	    make_request: Callable that returns a configured ``urllib.request.Request``.
	    timeout: Request timeout in seconds.
	    provider: Provider name for error messages (e.g. ``"Ollama"``).
	    path: API path for error messages (e.g. ``"/api/chat"``).
	    attempts: Maximum number of attempts (default 3).
	    backoff: Seconds to sleep between retries (default 0.5).

	Returns:
	    Parsed JSON response as a dict.

	Raises:
	    ValueError: With a descriptive error message after exhausting retries.
	"""
	last_error_message = ""

	for attempt in range(1, attempts + 1):
		request = make_request()
		try:
			with urllibRequest.urlopen(request, timeout=timeout) as response:
				raw = response.read().decode("utf-8")
				return parse_json_response(raw, path, provider)
		except urllibError.HTTPError as error:
			details = read_error_body(error)
			code = getattr(error, "code", "?")
			last_error_message = f"HTTP {code}. {details}" if details else f"HTTP {code}."
		except urllibError.URLError as error:
			reason = getattr(error, "reason", None)
			if isinstance(reason, socket.timeout) or "timed out" in str(reason or "").lower():
				last_error_message = (
					f"Timed out waiting for response from {provider} ({path}) "
					f"after {timeout:.1f}s."
				)
			else:
				last_error_message = (
					f"Unable to reach {provider} at {path}. "
					f"Reason: {str(reason or error).strip() or 'unknown network error'}."
				)
		except socket.timeout:
			last_error_message = (
				f"Timed out waiting for response from {provider} ({path}) "
				f"after {timeout:.1f}s."
			)
		except OSError as error:
			last_error_message = f"{provider} request failed: {error}"
		except UnicodeDecodeError as error:
			last_error_message = (
				f"{provider} returned non-UTF-8 content for {path}: {error}"
			)

		if attempt >= attempts:
			raise ValueError(
				f"{provider} request failed for {path} after {attempt} "
				f"attempt(s): {last_error_message}",
			)

		time.sleep(backoff)

	# Should not reach here, but satisfy the return type.
	raise ValueError(f"{provider} request failed for {path}: no response")
