# -*- coding: utf-8 -*-
from __future__ import annotations

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
			prompt_key="page_summary",
			llm_method="summarize",
			tools=(),
			requires_input=False,
		)
