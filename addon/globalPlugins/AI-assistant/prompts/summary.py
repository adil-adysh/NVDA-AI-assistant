# -*- coding: utf-8 -*-
from __future__ import annotations

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


def _bounded_structure_items(items: tuple[str, ...], field: str) -> tuple[str, ...]:
	"""Bound noisy controls before they reach the structure prompt."""
	limit = _STRUCTURE_ITEM_LIMITS.get(field)
	bounded = items if limit is None else items[:limit]
	compact = tuple(_compact_structure_label(item) for item in bounded)
	if limit is None or len(items) <= limit:
		return compact
	return (*compact, f"[additional {field} omitted: {len(items) - limit}]")


def _compact_structure_label(value: object) -> str:
	text = " ".join(str(value).split())
	if len(text) <= _MAX_STRUCTURE_LABEL_CHARS:
		return text
	return text[: _MAX_STRUCTURE_LABEL_CHARS - 1].rstrip() + "…"


def _bounded_headings(items: tuple[tuple[int | None, str], ...]) -> tuple[tuple[int | None, str], ...]:
	limit = _STRUCTURE_ITEM_LIMITS["headings"]
	bounded = tuple((level, _compact_structure_label(name)) for level, name in items[:limit])
	if len(items) <= limit:
		return bounded
	return (*bounded, (None, f"[additional headings omitted: {len(items) - limit}]"))


def _graph_section_context(context: ExtractionResult) -> tuple[tuple[str, tuple[str, ...]], ...]:
	"""Compact graph projection for prompts; live objects never enter prompts."""
	graph = context.graph
	if graph is None:
		return ()
	nodes = {node.id: node for node in graph.nodes}
	sections: list[tuple[str, tuple[str, ...]]] = []
	for section in graph.sections[:8]:
		members = tuple(
			f"{node.role}: {_compact_structure_label(node.name)}"
			for node_id in section.node_ids
			if (node := nodes.get(node_id)) is not None and node.name
		)[:6]
		sections.append((_compact_structure_label(section.title), members))
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


def build_extraction_structure_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	return build_structure_summary_prompt(context, language=language)


def build_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	if context.source == "browser":
		return build_browser_summary_prompt(context, language=language)
	if context.source == "terminal":
		return build_terminal_summary_prompt(context, language=language)
	return build_generic_summary_prompt(context, language=language)


def build_structure_summary_prompt(context: ExtractionResult, language: str | None = None) -> str:
	graph_structure = _graph_structure_context(context.graph) if context.graph and context.graph.nodes else None
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
		headings=_bounded_headings(tuple(headings)),
		links=_bounded_structure_items(tuple(links), "links"),
		buttons=_bounded_structure_items(tuple(buttons), "buttons"),
		landmarks=_bounded_structure_items(tuple(landmarks), "landmarks"),
		inputs=_bounded_structure_items(tuple(inputs), "inputs"),
		comboboxes=_bounded_structure_items(tuple(comboboxes), "comboboxes"),
		checkboxes=_bounded_structure_items(tuple(checkboxes), "checkboxes"),
		radios=_bounded_structure_items(tuple(radios), "radios"),
		graph_sections=_graph_section_context(context),
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
