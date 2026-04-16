# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..context.pipeline import ContextPipeline
from ..context.types import PromptContext
from ..service.llm import LLMService
from .types import UseCaseResult, UseCaseSpec

ContextEmitter = Callable[[str, str], None] | None


class UseCase(ABC):
	@property
	@abstractmethod
	def spec(self) -> UseCaseSpec:
		raise NotImplementedError

	@abstractmethod
	def execute(
		self,
		context_pipeline: ContextPipeline | None,
		llm_service: LLMService,
		emit: ContextEmitter = None,
		**kwargs: Any,
	) -> UseCaseResult:
		raise NotImplementedError

	def collect_prompt_context(self, context_pipeline: ContextPipeline | None, emit: ContextEmitter = None) -> PromptContext | None:
		if context_pipeline is None or not self.spec.context_profile:
			return None
		if emit is not None:
			emit("collecting_context", f"Collecting context for {self.spec.id}...")
		return context_pipeline.collect(use_case_id=self.spec.id, context_profile=self.spec.context_profile)
