# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.types import ExtractionResult
from .base import build_system_prompt_for_nvda_assistant, render_prompt_template


def build_extraction_summary_prompt(context: ExtractionResult) -> str:
    return build_summary_prompt(context)


def build_summary_prompt(context: ExtractionResult) -> str:
    if context.source == "browser":
        return build_browser_summary_prompt(context)
    if context.source == "terminal":
        return build_terminal_summary_prompt(context)
    return build_generic_summary_prompt(context)


def build_browser_summary_prompt(context: ExtractionResult) -> str:
    structure = context.structure
    return render_prompt_template(
        "summary_browser.jinja2",
        system_prompt=build_system_prompt_for_nvda_assistant(),
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


def build_terminal_summary_prompt(context: ExtractionResult) -> str:
    return render_prompt_template(
        "summary_terminal.jinja2",
        system_prompt=build_system_prompt_for_nvda_assistant(),
        app_title=context.app_title,
        title=context.title,
        trimmed="yes" if context.truncated else "no",
        text=context.text or "",
    )


def build_generic_summary_prompt(context: ExtractionResult) -> str:
    structure = context.structure
    return render_prompt_template(
        "summary_generic.jinja2",
        system_prompt=build_system_prompt_for_nvda_assistant(),
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
