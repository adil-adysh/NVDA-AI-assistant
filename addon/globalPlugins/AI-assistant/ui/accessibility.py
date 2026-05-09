# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable
import re


_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def coerce_announcement_text(*candidates: str | None) -> str | None:
	for candidate in candidates:
		if not isinstance(candidate, str):
			continue
		normalized = _WHITESPACE_PATTERN.sub(" ", candidate).strip()
		if normalized:
			return normalized
	return None


def strip_html_for_announcement(html: str | None) -> str | None:
	if not isinstance(html, str) or not html.strip():
		return None
	without_tags = _HTML_TAG_PATTERN.sub(" ", html)
	return coerce_announcement_text(without_tags)


def queue_response_announcement(
	queue_func: Callable[..., None],
	message_func: Callable[[str], None],
	*candidates: str | None,
) -> None:
	resolved_text = coerce_announcement_text(*candidates)
	if resolved_text is None:
		return
	queue_func(message_func, resolved_text)
