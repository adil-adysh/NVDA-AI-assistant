# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.types import FocusedTextSnapshot
from .base import build_system_prompt_for_nvda_assistant, render_prompt_template


def build_proofreading_prompt(
	context: FocusedTextSnapshot, language: str | None = None
) -> str:
	return render_prompt_template(
		"proofreading.jinja2",
		language=language,
		system_prompt=build_system_prompt_for_nvda_assistant(language=language),
		text=context.text,
		app_title=context.app_title,
		control_name=context.control_name,
	)
