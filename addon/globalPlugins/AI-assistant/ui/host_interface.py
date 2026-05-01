# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol


class HostTransport(Protocol):
	def send(self, message: bytes) -> bytes:
		raise NotImplementedError

	def send_and_receive(self, message: bytes) -> bytes:
		raise NotImplementedError


class UIHostRenderer(ABC):
	@abstractmethod
	def render_display_result(
		self,
		use_case_id: str | None,
		title: str,
		output_text: str | None = None,
		output_html: str | None = None,
		is_html: bool = False,
		success: bool = True,
		message: str | None = None,
		close_button: bool = True,
		copy_button: bool = True,
		copy_text: str | None = None,
		copy_markdown: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def open_chat(
		self,
		use_case_id: str | None,
		title: str,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
		coordinator: Any | None = None,
		tool_registry: Any | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def sync_session_state(self, metadata: dict[str, Any] | None = None) -> None:
		raise NotImplementedError

	@abstractmethod
	def chat_set_history(
		self,
		use_case_id: str | None,
		conversation_id: str,
		messages: list[dict[str, Any]],
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def chat_append(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message: dict[str, Any],
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def chat_update(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		content: list[dict[str, Any]] | str,
		status: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def chat_stream_begin(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		role: str = "assistant",
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def chat_stream_delta(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		delta: str,
		sequence: int,
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def chat_stream_end(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		content: list[dict[str, Any]] | str,
		status: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def chat_stream_abort(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		reason: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		raise NotImplementedError

	@abstractmethod
	def show_error(self, error_message: str, details: str | None = None) -> None:
		raise NotImplementedError

	@abstractmethod
	def show_progress(self, message: str) -> None:
		raise NotImplementedError

	@abstractmethod
	def close_window(self, reason: str | None = None) -> None:
		raise NotImplementedError
