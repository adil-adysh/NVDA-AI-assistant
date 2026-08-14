# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.types import ExtractionResult
from .base import build_system_prompt_for_nvda_assistant, render_prompt_template


_STRUCTURE_ITEM_LIMITS = {
	"links": 40,
	"buttons": 30,
	"inputs": 20,
	"comboboxes": 20,
	"checkboxes": 20,
	"radios": 20,
}


def _bounded_structure_items(items: tuple[str, ...], field: str) -> tuple[str, ...]:
	"""Bound noisy controls before they reach the structure prompt."""
	limit = _STRUCTURE_ITEM_LIMITS.get(field)
	if limit is None or len(items) <= limit:
		return items
	return (*items[:limit], f"[additional {field} omitted: {len(items) - limit}]")


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
		headings=structure.headings if structure else (),
		links=_bounded_structure_items(structure.links, "links") if structure else (),
		buttons=_bounded_structure_items(structure.buttons, "buttons") if structure else (),
		landmarks=structure.landmarks if structure else (),
		inputs=_bounded_structure_items(structure.inputs, "inputs") if structure else (),
		comboboxes=_bounded_structure_items(structure.comboboxes, "comboboxes") if structure else (),
		checkboxes=_bounded_structure_items(structure.checkboxes, "checkboxes") if structure else (),
		radios=_bounded_structure_items(structure.radios, "radios") if structure else (),
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
