# -*- coding: utf-8 -*-
"""Validation and deterministic fallback for structure-summary output."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..context.navigation import NavigationTarget


@dataclass(frozen=True, slots=True)
class StructureSummaryDestination:
	target_id: str
	reason: str


@dataclass(frozen=True, slots=True)
class StructureSummaryResponse:
	page_context: str | None
	destinations: tuple[StructureSummaryDestination, ...]
	omissions: str | None = None
	structured: bool = False


def parse_structure_summary_response(
	text: str,
	candidates: Iterable[NavigationTarget],
	*,
	max_destinations: int = 8,
) -> StructureSummaryResponse:
	"""Parse a provider response and keep only known target IDs.

	Providers currently expose text summaries rather than a structured-output
	API, so malformed JSON is expected. In that case the deterministic target
	list is the safe fallback; model text must never create a clickable target.
	"""
	candidate_list = tuple(candidates)
	by_id = {target.id: target for target in candidate_list}
	data = _load_json_object(text)
	if data is not None:
		destinations: list[StructureSummaryDestination] = []
		seen: set[str] = set()
		for item in data.get("destinations", ()):
			if not isinstance(item, dict):
				continue
			target_id = item.get("target_id")
			if not isinstance(target_id, str) or target_id not in by_id or target_id in seen:
				continue
			reason = item.get("reason")
			if not isinstance(reason, str) or not reason.strip():
				reason = by_id[target_id].reason
			destinations.append(StructureSummaryDestination(target_id, _clean(reason)))
			seen.add(target_id)
			if len(destinations) >= max_destinations:
				break
		if destinations or not candidate_list:
			return StructureSummaryResponse(
				page_context=_optional_text(data.get("page_context")),
				destinations=tuple(destinations),
				omissions=_optional_text(data.get("omissions")),
				structured=True,
			)

	return StructureSummaryResponse(
		page_context=None,
		destinations=tuple(
			StructureSummaryDestination(target.id, target.reason)
			for target in candidate_list[:max_destinations]
		),
		structured=False,
	)


def render_structure_summary(
	response: StructureSummaryResponse,
	candidates: Iterable[NavigationTarget],
) -> str:
	"""Render validated destinations into the user-facing result text."""
	by_id = {target.id: target for target in candidates}
	lines = ["Most useful places:", ""]
	if response.destinations:
		for destination in response.destinations:
			target = by_id.get(destination.target_id)
			if target is not None:
				lines.append(f"* {target.name} — {destination.reason}")
	else:
		lines.append("* No useful destinations were detected.")
	if response.page_context:
		lines.extend(("", "Page context:", "", f"* {response.page_context}"))
	if response.omissions:
		lines.extend(("", "Notable omissions:", "", f"* {response.omissions}"))
	return "\n".join(lines)


def _load_json_object(text: str) -> dict[str, Any] | None:
	value = (text or "").strip()
	if not value:
		return None
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError, json.JSONDecodeError):
		start = value.find("{")
		end = value.rfind("}")
		if start < 0 or end <= start:
			return None
		try:
			parsed = json.loads(value[start : end + 1])
		except (TypeError, ValueError, json.JSONDecodeError):
			return None
	return parsed if isinstance(parsed, dict) else None


def _optional_text(value: object) -> str | None:
	if not isinstance(value, str):
		return None
	value = _clean(value)
	return value or None


def _clean(value: str) -> str:
	return " ".join(value.split())
