# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any

from logHandler import log

from ..base_coordinator import BaseCoordinator
from ..core.canonical import Message, Tool
from ..core.message_transforms import build_user_message, message_to_chat_message
from ..core.messages import ChatMessage, LLMResponse
from ..core.events import ProgressHandler
from .llm import LLMService
from ..observability.reporter import MetricsReporter


class ChatCoordinator(BaseCoordinator):
	def __init__(
		self,
		client: LLMService,
		tool_executor: Any | None = None,
		metrics_reporter: MetricsReporter | None = None,
	) -> None:
		super().__init__(metrics_reporter)
		self._llm_service = client
		self._tool_executor = tool_executor
		self._history: list[ChatMessage] = []

	def send(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		progress: ProgressHandler | None = None,
	) -> LLMResponse:
		return self._send(messages, tools=tools, stream_handler=None, progress=progress)

	def send_message(
		self,
		text: str | None = None,
		image_base64: str | None = None,
		progress_callback: Callable[[str, int], None] | None = None,
		tools: list[dict[str, Any]] | None = None,
		progress: ProgressHandler | None = None,
	) -> str:
		user_message = self._build_user_message(text=text, image_base64=image_base64)
		canonical_tools = self._convert_tool_definitions(tools)
		response = self._send(
			[user_message],
			tools=canonical_tools,
			stream_handler=progress_callback,
			progress=progress,
		)
		return response.text

	def get_history(self) -> list[ChatMessage]:
		return list(self._history)

	def reset(self) -> None:
		self._history = []

	def _send(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
		progress: ProgressHandler | None = None,
	) -> LLMResponse:
		if not messages:
			raise ValueError("ChatCoordinator.send requires at least one message")

		self._append_history_from_messages(messages)
		if threading.current_thread() is threading.main_thread():
			log.warning("ChatCoordinator.send called on main thread; should be invoked from a background worker")

		response = self._llm_service.generate(
			messages=messages,
			tools=tools,
			stream_handler=stream_handler,
			progress=progress,
		)
		self._history.append(
			ChatMessage(
				role="assistant",
				content=response.text,
			)
		)
		return response

	def _append_history_from_messages(self, messages: list[Message]) -> None:
		for message in messages:
			self._history.append(message_to_chat_message(message))

	def _build_user_message(self, text: str | None, image_base64: str | None) -> Message:
		return build_user_message(text=text, image_base64=image_base64)

	def _convert_tool_definitions(self, tools: list[dict[str, Any]] | None) -> list[Tool] | None:
		if tools is None:
			return None

		canonical_tools: list[Tool] = []
		for tool_def in tools:
			function_payload = None
			if tool_def.get("type") == "function" and isinstance(tool_def.get("function"), dict):
				function_payload = tool_def["function"]
			if function_payload is None:
				continue
			name = str(function_payload.get("name", "")).strip()
			if not name:
				continue
			description = str(function_payload.get("description", ""))
			parameters = function_payload.get("parameters") if isinstance(function_payload.get("parameters"), dict) else {}
			required = tuple(item for item in parameters.get("required", []) if isinstance(item, str)) if isinstance(parameters, dict) else ()
			canonical_tools.append(
				Tool(
					name=name,
					description=description,
					parameters=parameters,
					required=required,
				)
			)
		return canonical_tools if canonical_tools else None
