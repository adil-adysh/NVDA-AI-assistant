# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.prompt.defaults import PAGE_SUMMARY_KEY
from ..context.types import APP, PAGE
from .prompt_driven import PromptDrivenUseCase
from .types import UseCaseSpec


class SummaryUseCase(PromptDrivenUseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="summary",
			description="Summarize the current page content.",
			context_profile=(APP, PAGE),
			builtin_prompt_name=PAGE_SUMMARY_KEY,
			llm_method="summarize",
			tools=(),
			requires_input=False,
		)
