# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.types import ExtractionResult
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
	structure = context.structure
	return render_prompt_template(
		"structure_summary.jinja2",
		language=language,
		system_prompt=build_system_prompt_for_nvda_assistant(language=language),
		app_title=context.app_title,
		title=context.title,
		source=context.source,
		trimmed="yes" if context.truncated else "no",
		headings=_bounded_headings(structure.headings) if structure else (),
		links=_bounded_structure_items(structure.links, "links") if structure else (),
		buttons=_bounded_structure_items(structure.buttons, "buttons") if structure else (),
		landmarks=_bounded_structure_items(structure.landmarks, "landmarks") if structure else (),
		inputs=_bounded_structure_items(structure.inputs, "inputs") if structure else (),
		comboboxes=_bounded_structure_items(structure.comboboxes, "comboboxes") if structure else (),
		checkboxes=_bounded_structure_items(structure.checkboxes, "checkboxes") if structure else (),
		radios=_bounded_structure_items(structure.radios, "radios") if structure else (),
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
