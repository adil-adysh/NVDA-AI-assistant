"""Pure filtering and display helpers for the MCP tool list.

Kept free of wx so the approval and search rules can be tested without NVDA.
Server annotations are untrusted display data: this module uses them to filter
and to make bulk approval explicit, never to authorize a call.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

FILTER_ALL = "all"
FILTER_APPROVED = "approved"
FILTER_DENIED = "denied"
FILTER_READ_ONLY = "read_only"


def safe_text(value: object, limit: int | None = None) -> str:
	"""Flatten control characters and bound untrusted text for display."""

	if not isinstance(value, str):
		return ""
	text = " ".join("".join(char if char.isprintable() else " " for char in value).split())
	if limit is not None:
		return text[:limit]
	return text


def tool_heading(definition: object) -> str:
	"""The human-facing title if present, otherwise the provider tool name."""

	title = getattr(definition, "display_title", None)
	if isinstance(title, str) and title.strip():
		return safe_text(title, 200)
	name = getattr(definition, "provider_tool_name", None) or getattr(definition, "name", "")
	return safe_text(name, 200)


def declares_read_only(definition: object) -> bool:
	"""Whether the server claims this tool is read-only.

	The claim is untrusted. A destructive hint wins over a contradictory
	read-only hint so a destructive tool cannot be swept into a bulk approval.
	"""

	if declares_destructive(definition):
		return False
	annotations = getattr(definition, "annotations", None)
	return getattr(annotations, "read_only_hint", None) is True


def declares_destructive(definition: object) -> bool:
	annotations = getattr(definition, "annotations", None)
	return getattr(annotations, "destructive_hint", None) is True


def _word_hit(word: str, text: str) -> bool:
	return re.search(r"(?<![a-z0-9])" + re.escape(word), text) is not None


def searchable_text(definition: object) -> str:
	parts = [
		str(getattr(definition, "name", "") or ""),
		str(getattr(definition, "provider_tool_name", "") or ""),
		str(getattr(definition, "display_title", "") or ""),
		str(getattr(definition, "description", "") or ""),
	]
	metadata = getattr(definition, "metadata", None)
	if isinstance(metadata, Mapping):
		parts.extend(str(value) for value in metadata.values() if isinstance(value, str))
	return " ".join(parts).casefold()


def matches_filter(
	definition: object,
	approved_tool_ids: Iterable[str],
	query: str,
	filter_mode: str,
) -> bool:
	"""Whether one tool is visible under the current search and filter."""

	tool_id = str(getattr(definition, "tool_id", "") or "")
	approved = tool_id in approved_tool_ids
	if filter_mode == FILTER_APPROVED and not approved:
		return False
	if filter_mode == FILTER_DENIED and approved:
		return False
	if filter_mode == FILTER_READ_ONLY and not declares_read_only(definition):
		return False

	words = [word for word in str(query or "").casefold().split() if word]
	if not words:
		return True
	text = searchable_text(definition)
	return all(_word_hit(word, text) for word in words)


def visible_definitions(
	definitions: Iterable[object],
	approved_tool_ids: Iterable[str],
	query: str = "",
	filter_mode: str = FILTER_ALL,
) -> list[object]:
	approved = frozenset(approved_tool_ids)
	return [
		definition for definition in definitions if matches_filter(definition, approved, query, filter_mode)
	]


def unapproved_read_only(definitions: Iterable[object], approved_tool_ids: Iterable[str]) -> list[object]:
	"""Tools eligible for one explicit bulk approval.

	Only server-declared read-only, non-destructive tools are returned. The UI
	must still warn that the declaration is untrusted.
	"""

	approved = frozenset(approved_tool_ids)
	return [
		definition
		for definition in definitions
		if str(getattr(definition, "tool_id", "") or "") not in approved and declares_read_only(definition)
	]


def _json_ready(value: object) -> object:
	if isinstance(value, Mapping):
		return {str(key): _json_ready(item) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		return [_json_ready(item) for item in value]
	return value


def details_text(definition: object, approved: bool) -> str:
	"""Full details and input schema for the selected tool."""

	lines = [
		f"Tool: {tool_heading(definition)}",
		f"Name: {safe_text(getattr(definition, 'provider_tool_name', '') or getattr(definition, 'name', ''))}",
		f"Status: {'approved' if approved else 'denied'}",
		f"Read-only claim: {'yes' if declares_read_only(definition) else 'no or conflicting'}",
		f"Destructive claim: {'yes' if declares_destructive(definition) else 'no'}",
		"",
		"Description:",
		safe_text(getattr(definition, "description", ""), 4000) or "(none provided)",
		"",
		"Input schema:",
	]
	schema = getattr(definition, "input_schema", None)
	try:
		rendered = json.dumps(
			_json_ready(schema),
			indent=2,
			ensure_ascii=False,
			sort_keys=True,
			default=str,
		)
	except (TypeError, ValueError):
		rendered = str(schema)
	return "\n".join(lines) + "\n" + rendered[:12000]
