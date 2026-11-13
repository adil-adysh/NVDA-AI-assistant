# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Protocol

from ..config.settings import is_streaming_enabled
from ..core.cancellation import check_cancelled, record_partial
from ..core.events import ProgressEvent, ProgressHandler
from ..core.canonical import Message, Tool
from ..core.message_transforms import build_assistant_message, build_tool_result_message_from_result
from ..core.messages import LLMResponse, SummaryResponse
from ..core.translation import _
from ..providers.interfaces import LLMProvider, PartialCallback, ProgressCallback, ProviderModelInfo
from ..tools import (
	ToolBudgetExceeded,
	ToolCatalogSnapshot,
	ToolExecutionResult,
	ToolExecutionTracker,
	ToolExecutor,
)
from .chat.types import ConversationTurnResult


class LLMService(Protocol):
	def provider_name(self) -> str:
		...

	def supports_streaming(self) -> bool:
		...

	def supports_image_description(self) -> bool:
		...

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		...

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		...

	def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
		...

	def summarize_structured(
		self,
		prompt: str,
		schema: dict[str, object],
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		...

	def describe_image(
		self,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		...

	def generate(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
		progress: ProgressHandler | None = None,
	) -> LLMResponse:
		...

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		...

	def close(self) -> None:
		...


class ProviderLLMService:
	MAX_TOOL_STEPS = 5

	def __init__(self, provider: LLMProvider, tool_executor: ToolExecutor | None = None) -> None:
		self._provider = provider
		self._tool_executor = tool_executor

	def provider_name(self) -> str:
		return self._provider.provider_name()

	def supports_streaming(self) -> bool:
		return self._provider.supports_streaming()

	def supports_image_description(self) -> bool:
		return self._provider.supports_image_description()

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		return self._provider.list_models()

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		return self._provider.get_model_info(model_name=model_name)

	def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
		check_cancelled()
		effective = self._cancellable_stream(stream_handler) if is_streaming_enabled() else None
		return self._request(lambda: self._provider.summarize(prompt, stream_handler=effective))

	def summarize_structured(
		self,
		prompt: str,
		schema: dict[str, object],
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		# Structured responses are intentionally non-streaming: emitting partial
		# JSON would not be a valid displayable structure-summary response.
		return self._request(lambda: self._provider.summarize_structured(
			prompt, schema=schema, stream_handler=None
		))

	def describe_image(
		self,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		check_cancelled()
		effective = self._cancellable_stream(stream_handler) if is_streaming_enabled() else None
		return self._request(lambda: self._provider.describe_image(
			image_base64=image_base64,
			prompt=prompt,
			stream_handler=effective,
		))

	def generate(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
		progress: ProgressHandler | None = None,
	) -> LLMResponse:
		return self.generate_with_transcript(
			messages=messages,
			tools=tools,
			stream_handler=stream_handler,
			progress=progress,
		).response

	def generate_with_transcript(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
		progress: ProgressHandler | None = None,
		tool_catalog: ToolCatalogSnapshot | None = None,
		tracker: ToolExecutionTracker | None = None,
	) -> ConversationTurnResult:
		check_cancelled()
		canonical_messages = list(messages)
		generated_messages: list[Message] = []

		def emit(stage: str, message: str) -> None:
			if progress is not None:
				progress(ProgressEvent(stage=stage, message=message))

		_streaming_enabled = is_streaming_enabled()

		def stream_adapter(partial_text: str, generated_chars: int) -> None:
			record_partial(partial_text, generated_chars)
			if progress is not None:
				emit("streaming", partial_text)
			if stream_handler is not None:
				stream_handler(partial_text, generated_chars)

		_use_streaming = _streaming_enabled and (stream_handler is not None or progress is not None)

		def request() -> LLMResponse:
			return self._request(lambda: self._provider.generate(
				messages=canonical_messages,
				tools=tools,
				stream_handler=stream_adapter if _use_streaming else None,
			))

		emit("llm_request", f"Generating response with {self.provider_name()}...")
		response = request()
		assistant_message = build_assistant_message(text=response.text, tool_calls=response.tool_calls)
		generated_messages.append(assistant_message)
		if self._tool_executor is None:
			return ConversationTurnResult(response=response, messages=tuple(generated_messages))

		effective_tracker = tracker or self._new_tracker()
		loop_limit_reached = False
		while response.tool_calls:
			try:
				effective_tracker.begin_iteration()
			except ToolBudgetExceeded:
				loop_limit_reached = True
				break
			check_cancelled()
			# The assistant message carrying tool_calls must precede the tool
			# results in the provider-visible history; otherwise OpenAI-compat
			# servers reject the follow-up request (tool result without a
			# matching assistant tool-call message).
			canonical_messages.append(assistant_message)
			emit("tool_execution", f"Executing {len(response.tool_calls)} tool call(s)...")
			tool_messages: list[ToolExecutionResult] = []
			for tool_call in response.tool_calls:
				check_cancelled()
				tool_messages.extend(
					self._request(
						lambda call=tool_call: self._execute_tool_calls(
							[call], tool_catalog, effective_tracker
						)
					)
				)
			check_cancelled()
			canonical_tool_messages = self._convert_tool_messages(tool_messages)
			canonical_messages.extend(canonical_tool_messages)
			generated_messages.extend(canonical_tool_messages)
			emit("tool_execution", "Tool execution complete.")
			emit("llm_request", f"Continuing response with {self.provider_name()}...")
			response = request()
			assistant_message = build_assistant_message(text=response.text, tool_calls=response.tool_calls)
			generated_messages.append(assistant_message)

		if loop_limit_reached:
			response, closing_messages = self._close_pending_tool_calls(response)
			canonical_messages.extend(closing_messages)
			generated_messages.extend(closing_messages)
			generated_messages.append(build_assistant_message(text=response.text))

		return ConversationTurnResult(response=response, messages=tuple(generated_messages))

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		return self._provider.ensure_model_available(on_progress=on_progress)

	@staticmethod
	def _request(operation):
		check_cancelled()
		try:
			result = operation()
		except Exception:
			# HTTP adapters may wrap callback exceptions as provider errors.
			check_cancelled()
			raise
		check_cancelled()
		return result

	@staticmethod
	def _cancellable_stream(handler):
		if handler is None:
			return None
		def callback(text, count):
			record_partial(text, count)
			handler(text, count)
		return callback

	def _new_tracker(self) -> ToolExecutionTracker:
		factory = getattr(self._tool_executor, "new_tracker", None)
		if callable(factory):
			return factory()
		return ToolExecutionTracker()

	def _execute_tool_calls(
		self,
		tool_calls: list,
		tool_catalog: ToolCatalogSnapshot | None,
		tracker: ToolExecutionTracker,
	) -> list[ToolExecutionResult]:
		executor = self._tool_executor
		if executor is None:
			return []
		try:
			signature = inspect.signature(executor.execute_tool_calls)
		except (TypeError, ValueError):
			return executor.execute_tool_calls(tool_calls)
		kwargs = {}
		if "snapshot" in signature.parameters:
			kwargs["snapshot"] = tool_catalog
		if "tracker" in signature.parameters:
			kwargs["tracker"] = tracker
		return executor.execute_tool_calls(tool_calls, **kwargs)

	def close(self) -> None:
		self._provider.close()

	def _convert_tool_messages(self, tool_messages: list[ToolExecutionResult]) -> list[Message]:
		return [build_tool_result_message_from_result(result) for result in tool_messages]

	def _close_pending_tool_calls(
		self,
		response: LLMResponse,
	) -> tuple[LLMResponse, list[Message]]:
		"""Resolve outstanding tool calls after the iteration limit.

		Leaving assistant ``tool_calls`` without matching tool results would make
		the persisted transcript invalid for the next provider request.
		"""
		results = [
			ToolExecutionResult(
				tool_name=call.name,
				tool_call_id=call.id,
				ok=False,
				error_category="budget_exceeded",
				error_source="host",
				error_message="Tool iteration limit reached; the call was not executed.",
			)
			for call in (response.tool_calls or [])
		]
		messages = self._convert_tool_messages(results)
		message_text = response.text.strip() if isinstance(response.text, str) else ""
		if not message_text:
			message_text = _("Tool execution limit reached. Ask again with a narrower request.")
		raw = dict(response.raw) if isinstance(response.raw, dict) else {"raw": response.raw}
		raw["tool_loop_limit_reached"] = True
		return (
			LLMResponse(text=message_text, model=response.model, raw=raw, tool_calls=None),
			messages,
		)
