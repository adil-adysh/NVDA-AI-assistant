# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..core.events import ProgressEvent, ProgressHandler
from ..core.canonical import Message, Tool
from ..core.message_transforms import build_assistant_message, build_tool_result_message
from ..core.messages import LLMResponse, SummaryResponse, ToolExecutionResult
from ..providers.interfaces import LLMProvider, PartialCallback, ProgressCallback, ProviderModelInfo
from ..tools import ToolExecutor
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
		return self._provider.summarize(prompt, stream_handler=stream_handler)

	def describe_image(
		self,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		return self._provider.describe_image(
			image_base64=image_base64,
			prompt=prompt,
			stream_handler=stream_handler,
		)

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
	) -> ConversationTurnResult:
		canonical_messages = list(messages)
		generated_messages: list[Message] = []

		def emit(stage: str, message: str) -> None:
			if progress is not None:
				progress(ProgressEvent(stage=stage, message=message))

		def stream_adapter(partial_text: str, generated_chars: int) -> None:
			if progress is not None:
				emit("streaming", partial_text)
			if stream_handler is not None:
				stream_handler(partial_text, generated_chars)

		emit("llm_request", f"Generating response with {self.provider_name()}...")
		response = self._provider.generate(
			messages=canonical_messages,
			tools=tools,
			stream_handler=stream_adapter if (stream_handler is not None or progress is not None) else None,
		)
		generated_messages.append(build_assistant_message(text=response.text, tool_calls=response.tool_calls))
		if self._tool_executor is None:
			return ConversationTurnResult(response=response, messages=tuple(generated_messages))

		steps = 0
		while response.tool_calls and steps < self.MAX_TOOL_STEPS:
			emit("tool_execution", f"Executing {len(response.tool_calls)} tool call(s)...")
			tool_messages = self._tool_executor.execute_tool_calls(response.tool_calls)
			canonical_tool_messages = self._convert_tool_messages(tool_messages)
			canonical_messages.extend(canonical_tool_messages)
			generated_messages.extend(canonical_tool_messages)
			emit("tool_execution", "Tool execution complete.")
			emit("llm_request", f"Continuing response with {self.provider_name()}...")
			response = self._provider.generate(
				messages=canonical_messages,
				tools=tools,
				stream_handler=stream_adapter if (stream_handler is not None or progress is not None) else None,
			)
			generated_messages.append(build_assistant_message(text=response.text, tool_calls=response.tool_calls))
			steps += 1

		return ConversationTurnResult(response=response, messages=tuple(generated_messages))

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		return self._provider.ensure_model_available(on_progress=on_progress)

	def close(self) -> None:
		self._provider.close()

	def _convert_tool_messages(self, tool_messages: list[ToolExecutionResult]) -> list[Message]:
		return [build_tool_result_message(tool_message.tool_name, tool_message.content) for tool_message in tool_messages]
