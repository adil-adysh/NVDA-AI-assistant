# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.prompt.defaults import IMAGE_DESCRIPTION_KEY
from ..context.types import IMAGE
from .prompt_driven import PromptDrivenUseCase
from .types import UseCaseSpec


class ImageDescriptionUseCase(PromptDrivenUseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="describe_image",
			description="Describe the current foreground window screenshot.",
			context_profile=(IMAGE,),
			builtin_prompt_name=IMAGE_DESCRIPTION_KEY,
			llm_method="describe_image",
			tools=(),
			requires_input=False,
		)
