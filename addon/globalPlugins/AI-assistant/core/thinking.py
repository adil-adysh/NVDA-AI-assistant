# -*- coding: utf-8 -*-
"""Helpers for separating provider reasoning traces from answer text."""
from __future__ import annotations

from typing import Any


def extract_thinking_trace(response: Any) -> str | None:
	"""Return a structured reasoning trace exposed by a provider response."""
	raw = getattr(response, "raw", None)
	if raw is None:
		return None
	if isinstance(raw, dict):
		message = raw.get("message")
		if isinstance(message, dict):
			thinking = message.get("thinking")
			if isinstance(thinking, str) and thinking.strip():
				return thinking
		choices = raw.get("choices")
		if isinstance(choices, list):
			for choice in choices:
				message = choice.get("message") if isinstance(choice, dict) else None
				if isinstance(message, dict) and isinstance(message.get("reasoning_content"), str):
					return message["reasoning_content"]
		chunks = raw.get("chunks")
		if isinstance(chunks, list):
			parts = [
				str(choice["delta"]["reasoning_content"])
				for chunk in chunks
				if isinstance(chunk, dict)
				for choice in (chunk.get("choices") or [])
				if isinstance(choice, dict)
				and isinstance(choice.get("delta"), dict)
				and isinstance(choice["delta"].get("reasoning_content"), str)
			]
			return "".join(parts) or None
	metadata = getattr(raw, "metadata", None)
	if isinstance(metadata, dict):
		thinking_trace = metadata.get("thinking_trace")
		return thinking_trace if isinstance(thinking_trace, str) else None
	return None
