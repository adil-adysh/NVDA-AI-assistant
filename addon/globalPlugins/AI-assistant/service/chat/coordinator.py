# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable, Sequence
import threading
from typing import Any
from uuid import uuid4

from logHandler import log

from ..base import BaseCoordinator
from ...core.canonical import Message, Tool
from ...core.message_transforms import build_user_message
from ...context.budget import (
	ApproximateTokenCounter,
	ContextBudgetError,
	ContextWindowBudget,
)
from ...core.messages import ChatMessage, LLMResponse
from ...core.events import ProgressHandler
from ..llm import ProviderLLMService
from ...providers.interfaces import ProviderModelInfo
from ...observability.reporter import MetricsReporter
from .projector import project_chat_history, project_chat_history_transport
from .repository import ConversationRepository, ConversationSummary
from .session import ConversationSession
from .transaction import ChatTurnTransaction


# ChatCoordinator drives chat synchronously through send()/send_message() and
# never uses BaseCoordinator's background-task hooks (_run_task_logic,
# _present_result, _format_progress_message), so those stay unimplemented.
class ChatCoordinator(BaseCoordinator):  # pylint: disable=abstract-method
	def __init__(
		self,
		client: ProviderLLMService,
		metrics_reporter: MetricsReporter | None = None,
		session_factory: Callable[[], ConversationSession] = ConversationSession,
		repository: ConversationRepository | None = None,
		conversation_id_factory: Callable[[], str] | None = None,
		history_projector: Callable[[list[Message]], list[ChatMessage]] = project_chat_history,
		history_transport_projector: Callable[
			[list[Message]], list[dict[str, Any]]
		] = project_chat_history_transport,
		page_context_provider: object | None = None,
	) -> None:
		super().__init__(metrics_reporter)
		self._llm_service = client
		self._session = session_factory()
		self._session_factory = session_factory
		self._session_lock = threading.RLock()
		self._session_generation = 0
		self._repository = repository
		self._conversation_id_factory = conversation_id_factory or (lambda: str(uuid4()))
		self._active_conversation_id: str | None = None
		self._last_turn_committed: bool = False
		self._history_projector = history_projector
		self._history_transport_projector = history_transport_projector
		self._page_context_provider = page_context_provider

	def set_page_context(self, context: Any, conversation_id: str) -> None:
		provider = self._page_context_provider
		if provider is not None:
			provider.set(context, conversation_id)

	def clear_page_context(self) -> None:
		provider = self._page_context_provider
		if provider is not None:
			provider.clear()

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
	) -> LLMResponse:
		user_message = self._build_user_message(text=text, image_base64=image_base64)
		canonical_tools = self._convert_tool_definitions(tools)
		transient_context: tuple[Message, ...] = ()
		provider = self._page_context_provider
		if provider is not None and isinstance(text, str) and text.strip():
			retrieve = getattr(provider, "retrieve", None)
			if callable(retrieve):
				with self._session_lock:
					prior_messages = tuple(self._session.snapshot())
				context_text = retrieve(
					text,
					self.get_active_conversation_id(),
					prompt_budget=self._build_context_budget(
						reserved_input_tokens=self._estimate_messages_tokens(
							(*prior_messages, user_message)
						)
					),
				)
				if isinstance(context_text, str) and context_text.strip():
					transient_context = (build_user_message(text=context_text),)
		transaction, generation = self._begin_transaction(
			(user_message,), transient_context_messages=transient_context
		)
		log.debug(
			"ChatCoordinator.send_message starting: text=%r image_attached=%s tools=%s",
			text,
			image_base64 is not None,
			[tool.get("function", {}).get("name") for tool in tools] if tools else None,
		)
		response = self._send_transaction(
			transaction,
			generation=generation,
			tools=canonical_tools,
			stream_handler=progress_callback,
			progress=progress,
		)
		log.debug(
			"ChatCoordinator.send_message finished: response_text=%r tool_calls=%s",
			response.text,
			[tc.name for tc in response.tool_calls] if response.tool_calls else None,
		)
		return response

	def get_history(self) -> list[ChatMessage]:
		with self._session_lock:
			return self._history_projector(self._session.snapshot())

	def get_history_transport(self) -> list[dict[str, Any]]:
		with self._session_lock:
			return self._history_transport_projector(self._session.snapshot())

	def get_active_conversation_id(self) -> str | None:
		with self._session_lock:
			return self._active_conversation_id

	def activate_conversation(
		self,
		conversation_id: str | None = None,
		seed_messages: Sequence[Message] = (),
	) -> str:
		self.clear_page_context()
		with self._session_lock:
			resolved_conversation_id = (
				conversation_id.strip()
				if isinstance(conversation_id, str) and conversation_id.strip()
				else self._conversation_id_factory()
			)
			previous_conversation_id = self._active_conversation_id
			previous_messages = self._session.snapshot()
			if previous_conversation_id and previous_conversation_id != resolved_conversation_id:
				self._persist_conversation_locked(
					previous_conversation_id, previous_messages, delete_if_empty=False
				)
			self._active_conversation_id = resolved_conversation_id
			self._session_generation += 1
			if self._repository is not None and self._repository.exists(resolved_conversation_id):
				self._session = self._repository.load(resolved_conversation_id)
			else:
				self._session = self._session_factory()
			if seed_messages:
				self._session.extend(seed_messages)
			self._persist_locked()
			return resolved_conversation_id

	def list_conversations(self) -> list[ConversationSummary]:
		if self._repository is None:
			return []
		with self._session_lock:
			return self._repository.list_summaries()

	def delete_conversation(self, conversation_id: str) -> bool:
		if self._repository is None:
			return False
		with self._session_lock:
			deleted = self._repository.delete(conversation_id)
			if deleted and conversation_id == self._active_conversation_id:
				self._active_conversation_id = None
				self._session = self._session_factory()
				self._session_generation += 1
			return deleted

	def reset(self) -> None:
		self.clear_page_context()
		with self._session_lock:
			self._session.reset()
			self._session_generation += 1
			self._persist_locked()

	def seed_history(self, messages: Sequence[Message]) -> None:
		if not messages:
			return
		with self._session_lock:
			self._session.extend(messages)
			self._persist_locked()

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		return self._llm_service.list_models()

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		return self._llm_service.get_model_info(model_name=model_name)

	def _build_context_budget(self, reserved_input_tokens: int = 0) -> ContextWindowBudget:
		model_info = None
		try:
			model_info = self._llm_service.get_model_info()
		except Exception:
			log.debug("Unable to resolve chat model context metadata", exc_info=True)
		context_window = getattr(model_info, "context_window", None) or 8192
		output_limit = getattr(model_info, "output_token_limit", None)
		reserved_output = 1024
		if isinstance(output_limit, int) and output_limit > 0:
			reserved_output = min(reserved_output, output_limit)
		return ContextWindowBudget(
			context_window_tokens=max(1, context_window),
			reserved_output_tokens=reserved_output,
			safety_margin_tokens=256,
			reserved_input_tokens=max(0, reserved_input_tokens),
		)

	@staticmethod
	def _estimate_messages_tokens(messages: Sequence[Message]) -> int:
		counter = ApproximateTokenCounter()
		# Provider serializers add different framing overhead; the shared safety
		# margin remains authoritative for the remaining provider-specific cost.
		return sum(
			4 + sum(counter.count(part.text or "") for part in message.parts)
			for message in messages
		)

	def _begin_transaction(
		self,
		staged_messages: tuple[Message, ...],
		transient_context_messages: tuple[Message, ...] = (),
	) -> tuple[ChatTurnTransaction, int]:
		with self._session_lock:
			generation = self._session_generation
			prior_messages = tuple(self._session.snapshot())
			return ChatTurnTransaction(
				prior_messages=prior_messages,
				staged_messages=staged_messages,
				transient_context_messages=transient_context_messages,
			), generation

	def _send_transaction(
		self,
		transaction: ChatTurnTransaction,
		generation: int,
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
		progress: ProgressHandler | None = None,
	) -> LLMResponse:
		if threading.current_thread() is threading.main_thread():
			log.warning(
				"ChatCoordinator.send called on main thread; should be invoked from a background worker"
			)

		self._validate_transaction_budget(transaction)

		turn_result = self._llm_service.generate_with_transcript(
			messages=transaction.request_messages(),
			tools=tools,
			stream_handler=stream_handler,
			progress=progress,
		)
		with self._session_lock:
			if generation == self._session_generation:
				self._session.extend(transaction.committed_messages(turn_result.messages))
				self._persist_locked()
				self._last_turn_committed = True
			else:
				log.debug("Discarding stale chat turn after session reset")
				self._last_turn_committed = False
		return turn_result.response

	def _validate_transaction_budget(self, transaction: ChatTurnTransaction) -> None:
		budget = self._build_context_budget()
		tokens = self._estimate_messages_tokens(transaction.request_messages())
		if tokens > budget.input_token_limit:
			raise ContextBudgetError(
				"Chat transcript exceeds the available input budget: "
				f"{tokens} > {budget.input_token_limit} tokens"
			)

	def last_turn_committed(self) -> bool:
		"""Whether the most recently completed chat turn was committed to the session.

		A turn may be discarded when the conversation was switched, reset, or
		deleted while the LLM request was in flight (the session generation
		changed between the request and its completion).
		"""
		with self._session_lock:
			return self._last_turn_committed

	def _persist_locked(self) -> None:
		if (
			self._repository is None
			or not isinstance(self._active_conversation_id, str)
			or not self._active_conversation_id
		):
			return
		self._persist_conversation_locked(self._active_conversation_id, self._session.snapshot())

	def _persist_conversation_locked(
		self,
		conversation_id: str,
		messages: Sequence[Message],
		*,
		delete_if_empty: bool = True,
	) -> None:
		if self._repository is None or not conversation_id:
			return
		if messages:
			self._repository.save(conversation_id, messages)
			return
		if delete_if_empty:
			self._repository.delete(conversation_id)

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
			parameters = (
				function_payload.get("parameters")
				if isinstance(function_payload.get("parameters"), dict)
				else {}
			)
			required = (
				tuple(item for item in parameters.get("required", []) if isinstance(item, str))
				if isinstance(parameters, dict)
				else ()
			)
			canonical_tools.append(
				Tool(
					name=name,
					description=description,
					parameters=parameters,
					required=required,
				)
			)
		return canonical_tools if canonical_tools else None
