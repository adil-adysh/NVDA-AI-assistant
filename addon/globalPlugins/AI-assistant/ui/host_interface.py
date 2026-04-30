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
		copy_html: str | None = None,
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
	def show_error(self, error_message: str, details: str | None = None) -> None:
		raise NotImplementedError

	@abstractmethod
	def show_progress(self, message: str) -> None:
		raise NotImplementedError

	@abstractmethod
	def close_window(self, reason: str | None = None) -> None:
		raise NotImplementedError
