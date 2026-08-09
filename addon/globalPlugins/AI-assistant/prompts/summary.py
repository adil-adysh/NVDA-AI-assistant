# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.types import ExtractionResult
from .base import build_system_prompt_for_nvda_assistant, render_prompt_template


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
		links=structure.links if structure else (),
		buttons=structure.buttons if structure else (),
		landmarks=structure.landmarks if structure else (),
		inputs=structure.inputs if structure else (),
		comboboxes=structure.comboboxes if structure else (),
		checkboxes=structure.checkboxes if structure else (),
		radios=structure.radios if structure else (),
		text=context.text or "",
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
