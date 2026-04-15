# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any

from logHandler import log

from ..base import BaseCoordinator
from ...core.canonical import Message, Tool
from ...core.message_transforms import build_user_message
from ...core.messages import ChatMessage, LLMResponse
from ...core.events import ProgressHandler
from ..llm import ProviderLLMService
from ...observability.reporter import MetricsReporter
from .projector import project_chat_history
from .session import ConversationSession
from .transaction import ChatTurnTransaction


class ChatCoordinator(BaseCoordinator):
	def __init__(
		self,
		client: ProviderLLMService,
		metrics_reporter: MetricsReporter | None = None,
		session_factory: Callable[[], ConversationSession] = ConversationSession,
		history_projector: Callable[[list[Message]], list[ChatMessage]] = project_chat_history,
	) -> None:
		super().__init__(metrics_reporter)
		self._llm_service = client
		self._session = session_factory()
		self._session_lock = threading.RLock()
		self._session_generation = 0
		self._history_projector = history_projector

	def send(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		progress: ProgressHandler | None = None,
	) -> LLMResponse:
		if not messages:
			raise ValueError("ChatCoordinator.send requires at least one message")
		transaction, generation = self._begin_transaction(tuple(messages))
		return self._send_transaction(
			transaction,
			generation=generation,
			tools=tools,
			stream_handler=None,
			progress=progress,
		)

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
		transaction, generation = self._begin_transaction((user_message,))
		response = self._send_transaction(
			transaction,
			generation=generation,
			tools=canonical_tools,
			stream_handler=progress_callback,
			progress=progress,
		)
		return response.text

	def get_history(self) -> list[ChatMessage]:
		with self._session_lock:
			return self._history_projector(self._session.snapshot())

	def reset(self) -> None:
		with self._session_lock:
			self._session.reset()
			self._session_generation += 1

	def _begin_transaction(self, staged_messages: tuple[Message, ...]) -> tuple[ChatTurnTransaction, int]:
		with self._session_lock:
			generation = self._session_generation
			prior_messages = tuple(self._session.snapshot())
			return ChatTurnTransaction(prior_messages=prior_messages, staged_messages=staged_messages), generation

	def _send_transaction(
		self,
		transaction: ChatTurnTransaction,
		generation: int,
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
		progress: ProgressHandler | None = None,
	) -> LLMResponse:
		if threading.current_thread() is threading.main_thread():
			log.warning("ChatCoordinator.send called on main thread; should be invoked from a background worker")

		turn_result = self._llm_service.generate_with_transcript(
			messages=transaction.request_messages(),
			tools=tools,
			stream_handler=stream_handler,
			progress=progress,
		)
		with self._session_lock:
			if generation == self._session_generation:
				self._session.extend(transaction.committed_messages(turn_result.messages))
			else:
				log.debug("Discarding stale chat turn after session reset")
		return turn_result.response

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
