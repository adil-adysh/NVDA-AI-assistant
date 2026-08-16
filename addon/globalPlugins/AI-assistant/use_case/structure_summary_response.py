# -*- coding: utf-8 -*-
"""Validation and rendering for LLM-authored structure outlines."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..context.navigation import NavigationTarget


STRUCTURE_SUMMARY_JSON_SCHEMA: dict[str, object] = {
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"overview": {"type": ["string", "null"]},
		"sections": {"type": "array", "maxItems": 8, "items": {
			"type": "object", "additionalProperties": False,
			"properties": {
				"title": {"type": "string"},
				"target_id": {"type": ["string", "null"]},
				"summary": {"type": "string"},
				"important_targets": {"type": "array", "maxItems": 4, "items": {
					"type": "object", "additionalProperties": False,
					"properties": {"target_id": {"type": "string"}, "reason": {"type": "string"}},
					"required": ["target_id", "reason"],
				}},
			},
			"required": ["title", "target_id", "summary", "important_targets"],
		}},
		"omissions": {"type": ["string", "null"]},
	},
	"required": ["overview", "sections", "omissions"],
}


@dataclass(frozen=True, slots=True)
class StructureSummaryTarget:
	target_id: str
	reason: str


@dataclass(frozen=True, slots=True)
class StructureSummarySection:
	title: str
	target_id: str | None
	summary: str
	important_targets: tuple[StructureSummaryTarget, ...] = ()


@dataclass(frozen=True, slots=True)
class StructureSummaryResponse:
	overview: str | None
	sections: tuple[StructureSummarySection, ...]
	omissions: str | None = None
	structured: bool = False

	@property
	def page_context(self) -> str | None:
		return self.overview

	@property
	def destinations(self) -> tuple[StructureSummaryTarget, ...]:
		result: list[StructureSummaryTarget] = []
		seen: set[str] = set()
		for section in self.sections:
			if section.target_id and section.target_id not in seen:
				result.append(StructureSummaryTarget(section.target_id, section.summary or "Useful page section"))
				seen.add(section.target_id)
			for target in section.important_targets:
				if target.target_id not in seen:
					seen.add(target.target_id)
					result.append(target)
		return tuple(result)


def parse_structure_summary_response(
	text: str,
	candidates: Iterable[NavigationTarget],
	*,
	max_sections: int = 8,
	max_targets_per_section: int = 4,
) -> StructureSummaryResponse:
	"""Validate model grouping while allowing only real target IDs."""
	candidate_list = tuple(candidates)
	by_id = {target.id: target for target in candidate_list}
	data = _load_json_object(text)
	if data is not None:
		parsed = _parse_outline(data, by_id, max_sections, max_targets_per_section)
		if parsed is not None:
			return parsed
	return StructureSummaryResponse(
		overview=None,
		sections=_fallback_sections(candidate_list, max_sections, max_targets_per_section),
		structured=False,
	)


def _parse_outline(
	data: dict[str, Any],
	by_id: dict[str, NavigationTarget],
	max_sections: int,
	max_targets_per_section: int,
) -> StructureSummaryResponse | None:
	# Accept old provider responses during rollout.
	if "sections" not in data and "destinations" in data:
		targets = _parse_targets(data.get("destinations"), by_id, max_targets_per_section)
		if targets or not by_id:
			return StructureSummaryResponse(
				overview=_optional_text(data.get("page_context")),
				sections=(StructureSummarySection("Most useful places", None, "", targets),),
				omissions=_optional_text(data.get("omissions")),
				structured=True,
			)
		return None
	value = data.get("sections")
	if not isinstance(value, list):
		return None
	sections: list[StructureSummarySection] = []
	used_targets: set[str] = set()
	for item in value[:max_sections]:
		if not isinstance(item, dict):
			continue
		title = _optional_text(item.get("title"))
		if not title:
			continue
		target_id = item.get("target_id")
		if not isinstance(target_id, str) or target_id not in by_id:
			target_id = None
		targets: list[StructureSummaryTarget] = []
		for target in _parse_targets(item.get("important_targets"), by_id, max_targets_per_section):
			if target.target_id in used_targets:
				continue
			used_targets.add(target.target_id)
			targets.append(target)
		sections.append(StructureSummarySection(
			title, target_id, _optional_text(item.get("summary")) or "", tuple(targets)
		))
	if not sections and by_id:
		return None
	return StructureSummaryResponse(
		overview=_optional_text(data.get("overview")),
		sections=tuple(sections),
		omissions=_optional_text(data.get("omissions")),
		structured=True,
	)


def _parse_targets(value: object, by_id: dict[str, NavigationTarget], limit: int) -> tuple[StructureSummaryTarget, ...]:
	if not isinstance(value, list):
		return ()
	result: list[StructureSummaryTarget] = []
	seen: set[str] = set()
	for item in value:
		if not isinstance(item, dict):
			continue
		target_id = item.get("target_id")
		if not isinstance(target_id, str) or target_id not in by_id or target_id in seen:
			continue
		reason = _optional_text(item.get("reason")) or by_id[target_id].reason
		result.append(StructureSummaryTarget(target_id, _clean(reason)))
		seen.add(target_id)
		if len(result) >= limit:
			break
	return tuple(result)


def _fallback_sections(
	candidates: tuple[NavigationTarget, ...], max_sections: int, max_targets_per_section: int
) -> tuple[StructureSummarySection, ...]:
	sections = tuple(
		StructureSummarySection(target.name, target.id, target.reason)
		for target in candidates if target.kind == "section"
	)[:max_sections]
	if sections or not candidates:
		return sections
	return (StructureSummarySection(
		"Most useful places", None, "",
		tuple(StructureSummaryTarget(target.id, target.reason) for target in candidates[:max_targets_per_section]),
	),)


def render_structure_summary(response: StructureSummaryResponse, candidates: Iterable[NavigationTarget]) -> str:
	"""Render a brief orientation outline using only validated targets."""
	by_id = {target.id: target for target in candidates}
	lines: list[str] = []
	if response.overview:
		lines.extend(("Overview:", "", f"* {response.overview}"))
	for section in response.sections:
		lines.extend(("", f"{section.title}:"))
		if section.summary:
			lines.append(f"* {section.summary}")
		if section.target_id in by_id:
			lines.append(f"* {by_id[section.target_id].name} — {by_id[section.target_id].reason}")
		for target in section.important_targets:
			resolved = by_id.get(target.target_id)
			if resolved is not None:
				lines.append(f"* {resolved.name} — {target.reason}")
	if not lines:
		lines = ["No useful page structure was detected."]
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
		start, end = value.find("{"), value.rfind("}")
		if start < 0 or end <= start:
			return None
		try:
			parsed = json.loads(value[start:end + 1])
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
