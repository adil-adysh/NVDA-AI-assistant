# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re

from .candidate_base import CandidateExtractionContext
from .text_extractor import TextExtractor

MAX_PAGE_TEXT_CHARS = 120000
MIN_PAGE_TEXT_CHARS = 120
_ELLIPSIS_BLOCK = "\n\n[Content trimmed before summarization]\n\n"


def extract_text_from_object(obj: object, text_extractor: TextExtractor | None = None) -> str:
	"""Extract text from an NVDA object via TextInfo or fallback attributes."""
	if text_extractor is None:
		text_extractor = TextExtractor()
	return text_extractor.extract_text(obj) or ""


def normalize_extracted_text(text: str) -> str:
	"""Collapse excessive whitespace and blank lines."""
	text = re.sub(r"[ \t]+", " ", text)
	text = re.sub(r"\n{3,}", "\n\n", text)
	return text.strip()


def is_meaningful_text(text: str) -> bool:
	"""Check whether extracted text meets the minimum character threshold."""
	return len(text.strip()) >= MIN_PAGE_TEXT_CHARS


def trim_text(text: str) -> tuple[str, bool]:
	"""Truncate text that exceeds the maximum allowed length."""
	if len(text) <= MAX_PAGE_TEXT_CHARS:
		return text, False
	return text[:MAX_PAGE_TEXT_CHARS] + _ELLIPSIS_BLOCK, True


def text_signature(text: str) -> str:
	"""SHA-256 signature for deduplicating extracted text."""
	return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def extract_title(obj: object, context: CandidateExtractionContext) -> str:
	"""Extract a display title from an NVDA object or its foreground context."""
	for attr in ("name", "title", "description"):
		try:
			value = getattr(obj, attr, None)
		except Exception:
			value = None
		if isinstance(value, str) and value.strip():
			return value.strip()
	if context.foreground is not None:
		for attr in ("name", "title", "description"):
			try:
				value = getattr(context.foreground, attr, None)
			except Exception:
				value = None
			if isinstance(value, str) and value.strip():
				return value.strip()
	return ""


def extract_app_title(context: CandidateExtractionContext) -> str:
	"""Extract the application name from the extraction context."""
	if context.appName:
		return context.appName
	return ""
