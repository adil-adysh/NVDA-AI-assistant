# -*- coding: utf-8 -*-
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from ..context.pipeline import ContextPipeline
from ..core.events import ProgressEvent, ProgressHandler
from ..service import LLMService
from ..service.error_presentation import present_error
from .base import UseCase
from .registry import build_default_use_cases
from .types import UseCaseId, UseCaseResult, UseCaseSpec


class UseCaseEngine:
	def __init__(
		self,
		llm_service: LLMService,
		context_pipeline: ContextPipeline | None = None,
		use_cases: Sequence[UseCase] | None = None,
		context_reducer: object | None = None,
	) -> None:
		self._llm_service = llm_service
		self._context_pipeline = context_pipeline
		self._context_reducer = context_reducer
		self._use_cases = tuple(use_cases or build_default_use_cases())
		self._use_case_map = {use_case.spec.id: use_case for use_case in self._use_cases}
		self._specs = {use_case.spec.id: use_case.spec for use_case in self._use_cases}

	def get_spec(self, use_case_id: UseCaseId) -> UseCaseSpec:
		try:
			return self._specs[use_case_id]
		except KeyError as error:
			raise ValueError(f"Unknown use case: {use_case_id}") from error

	def execute(self, use_case_id: UseCaseId, progress: ProgressHandler | None = None, **kwargs: Any) -> UseCaseResult:
		def emit(stage: str, message: str) -> None:
			if progress is not None:
				progress(ProgressEvent(stage=stage, message=message))

		emit("start", f"Starting {use_case_id}")
		try:
			use_case = self._use_case_map.get(use_case_id)
			if use_case is None:
				raise ValueError(f"Unknown use case: {use_case_id}")
			result = use_case.execute(
				context_pipeline=self._context_pipeline,
				llm_service=self._llm_service,
				emit=emit,
				_context_reducer=self._context_reducer,
				**kwargs,
			)
		except Exception as error:
			emit("error", present_error(error).message)
			raise

		# Inject result_actions flag from the spec into metadata so the
		# presenter never needs a hardcoded use-case-ID list.  Done at the
		# engine level so it covers all use cases, even those that implement
		# execute() directly instead of using execute_prompted_use_case.
		spec = self._specs.get(use_case_id)
		if spec is not None and spec.result_actions and result is not None:
			meta = dict(result.metadata) if result.metadata else {}
			if not meta.get("result_actions"):
				meta["result_actions"] = True
				result = dataclasses.replace(result, metadata=meta)

		emit("complete", result.message or f"{use_case_id} complete")
		return result
