# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ..context.types import AccessibilityGraph, ExtractionResult
from .base import build_system_prompt_for_nvda_assistant, render_prompt_template


_STRUCTURE_ITEM_LIMITS = {
	"headings": 40,
	"landmarks": 12,
	"links": 40,
	"buttons": 30,
	"inputs": 20,
	"comboboxes": 20,
	"checkboxes": 20,
	"radios": 20,
}

_MAX_STRUCTURE_LABEL_CHARS = 80


@dataclass(frozen=True, slots=True)
class _StructurePromptLimits:
	max_sections: int
	max_members_per_section: int
	max_items: dict[str, int]
	max_label_chars: int


def _prompt_limits(input_token_budget: int | None) -> _StructurePromptLimits:
	"""Choose graph detail from the actual available input budget."""
	budget = input_token_budget if input_token_budget is not None else 4500
	if budget < 3500:
		return _StructurePromptLimits(4, 4, {
			"headings": 20, "landmarks": 8, "links": 20, "buttons": 15,
			"inputs": 10, "comboboxes": 10, "checkboxes": 10, "radios": 10,
		}, 64)
	if budget < 7000:
		return _StructurePromptLimits(8, 6, _STRUCTURE_ITEM_LIMITS, _MAX_STRUCTURE_LABEL_CHARS)
	if budget < 12000:
		return _StructurePromptLimits(12, 8, {
			key: value * 3 // 2 for key, value in _STRUCTURE_ITEM_LIMITS.items()
		}, 96)
	return _StructurePromptLimits(16, 10, {
			key: value * 2 for key, value in _STRUCTURE_ITEM_LIMITS.items()
	}, 112)


def _bounded_structure_items(
	items: tuple[str, ...],
	field: str,
	limits: _StructurePromptLimits,
) -> tuple[str, ...]:
	"""Bound noisy controls before they reach the structure prompt."""
	limit = limits.max_items.get(field)
	bounded = items if limit is None else items[:limit]
	compact = tuple(_compact_structure_label(item, limits.max_label_chars) for item in bounded)
	if limit is None or len(items) <= limit:
		return compact
	return (*compact, f"[additional {field} omitted: {len(items) - limit}]")


def _compact_structure_label(value: object, max_chars: int = _MAX_STRUCTURE_LABEL_CHARS) -> str:
	text = " ".join(str(value).split())
	if len(text) <= max_chars:
		return text
	return text[: max_chars - 1].rstrip() + "…"


def _bounded_headings(
	items: tuple[tuple[int | None, str], ...], limits: _StructurePromptLimits
) -> tuple[tuple[int | None, str], ...]:
	limit = limits.max_items["headings"]
	bounded = tuple(
		(level, _compact_structure_label(name, limits.max_label_chars))
		for level, name in items[:limit]
	)
	if len(items) <= limit:
		return bounded
	return (*bounded, (None, f"[additional headings omitted: {len(items) - limit}]"))


def _graph_section_context(
	context: ExtractionResult,
	limits: _StructurePromptLimits,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
	"""Compact graph projection for prompts; live objects never enter prompts."""
	graph = context.graph
	if graph is None:
		return ()
	nodes = {node.id: node for node in graph.nodes}
	sections: list[tuple[str, tuple[str, ...]]] = []
	for section in graph.sections[:limits.max_sections]:
		members = tuple(
			f"{node.role}: {_compact_structure_label(node.name, limits.max_label_chars)}"
			for node_id in section.node_ids
			if (node := nodes.get(node_id)) is not None and node.name
		)[:limits.max_members_per_section]
		sections.append((_compact_structure_label(section.title, limits.max_label_chars), members))
	return tuple(sections)


def _graph_structure_context(
	graph: AccessibilityGraph,
) -> dict[str, tuple[object, ...]]:
	"""Project the graph into the legacy template categories.

	The graph is authoritative for browser structure.  The category-shaped
	values are retained only because localized templates still render those
	sections; they are a bounded view of graph nodes, not a second source of
	truth.
	"""
	projected: dict[str, list[object]] = {
		"headings": [],
		"links": [],
		"buttons": [],
		"landmarks": [],
		"inputs": [],
		"comboboxes": [],
		"checkboxes": [],
		"radios": [],
	}
	for node in sorted(graph.nodes, key=lambda item: item.order):
		if not node.name:
			continue
		if node.role == "heading":
			projected["headings"].append((node.heading_level, node.name))
		elif node.role in {"link", "button", "landmark"}:
			projected[f"{node.role}s"].append(node.name)
		elif node.role == "formField":
			field_key = {
				"combobox": "comboboxes",
				"checkbox": "checkboxes",
				"radio": "radios",
			}.get(node.control_type or "", "inputs")
			projected[field_key].append(node.name)
	return {key: tuple(value) for key, value in projected.items()}


def build_extraction_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	return build_summary_prompt(context, language=language)


def build_extraction_structure_summary_prompt(
	context: ExtractionResult,
	language: str | None = None,
	input_token_budget: int | None = None,
) -> str:
	return build_structure_summary_prompt(
		context,
		language=language,
		input_token_budget=input_token_budget,
	)


def build_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	if context.source == "browser":
		return build_browser_summary_prompt(context, language=language)
	if context.source == "terminal":
		return build_terminal_summary_prompt(context, language=language)
	return build_generic_summary_prompt(context, language=language)


def build_structure_summary_prompt(
	context: ExtractionResult,
	language: str | None = None,
	input_token_budget: int | None = None,
) -> str:
	graph_structure = _graph_structure_context(context.graph) if context.graph and context.graph.nodes else None
	limits = _prompt_limits(input_token_budget)
	structure = context.structure
	if graph_structure is not None:
		# Use graph-derived values for every category when available.  This keeps
		# the existing localized templates stable while eliminating structure/
		# graph drift in browser prompts.
		get_items = graph_structure.get
		headings = get_items("headings", ())
		links = get_items("links", ())
		buttons = get_items("buttons", ())
		landmarks = get_items("landmarks", ())
		inputs = get_items("inputs", ())
		comboboxes = get_items("comboboxes", ())
		checkboxes = get_items("checkboxes", ())
		radios = get_items("radios", ())
	else:
		headings = structure.headings if structure else ()
		links = structure.links if structure else ()
		buttons = structure.buttons if structure else ()
		landmarks = structure.landmarks if structure else ()
		inputs = structure.inputs if structure else ()
		comboboxes = structure.comboboxes if structure else ()
		checkboxes = structure.checkboxes if structure else ()
		radios = structure.radios if structure else ()
	return render_prompt_template(
		"structure_summary.jinja2",
		language=language,
		system_prompt=build_system_prompt_for_nvda_assistant(language=language),
		app_title=context.app_title,
		title=context.title,
		source=context.source,
		trimmed="yes" if context.truncated else "no",
		headings=_bounded_headings(tuple(headings), limits),
		links=_bounded_structure_items(tuple(links), "links", limits),
		buttons=_bounded_structure_items(tuple(buttons), "buttons", limits),
		landmarks=_bounded_structure_items(tuple(landmarks), "landmarks", limits),
		inputs=_bounded_structure_items(tuple(inputs), "inputs", limits),
		comboboxes=_bounded_structure_items(tuple(comboboxes), "comboboxes", limits),
		checkboxes=_bounded_structure_items(tuple(checkboxes), "checkboxes", limits),
		radios=_bounded_structure_items(tuple(radios), "radios", limits),
		graph_sections=_graph_section_context(context, limits),
		# Structure summary is an inventory/outline task.  Passing article prose
		# invites the model to produce a normal topical summary instead.
		text="",
	)


def build_browser_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	structure = context.structure
	return render_prompt_template(
		"summary_browser.jinja2",
		language=language,
		system_prompt=build_system_prompt_for_nvda_assistant(language=language),
		app_title=context.app_title,
		title=context.title,
		trimmed="yes" if context.truncated else "no",
		headings=structure.headings if structure else (),
		links=structure.links if structure else (),
		buttons=structure.buttons if structure else (),
		landmarks=structure.landmarks if structure else (),
		inputs=structure.inputs if structure else (),
		comboboxes=structure.comboboxes if structure else (),
		checkboxes=structure.checkboxes if structure else (),
		radios=structure.radios if structure else (),
		text=context.text or "",
	)


def build_terminal_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	return render_prompt_template(
		"summary_terminal.jinja2",
		language=language,
		system_prompt=build_system_prompt_for_nvda_assistant(language=language),
		app_title=context.app_title,
		title=context.title,
		trimmed="yes" if context.truncated else "no",
		text=context.text or "",
	)


def build_generic_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	structure = context.structure
	return render_prompt_template(
		"summary_generic.jinja2",
		language=language,
		system_prompt=build_system_prompt_for_nvda_assistant(language=language),
		app_title=context.app_title,
		title=context.title,
		trimmed="yes" if context.truncated else "no",
		headings=structure.headings if structure else (),
		links=structure.links if structure else (),
		buttons=structure.buttons if structure else (),
		landmarks=structure.landmarks if structure else (),
		inputs=structure.inputs if structure else (),
		comboboxes=structure.comboboxes if structure else (),
		checkboxes=structure.checkboxes if structure else (),
		radios=structure.radios if structure else (),
		text=context.text or "",
	)
