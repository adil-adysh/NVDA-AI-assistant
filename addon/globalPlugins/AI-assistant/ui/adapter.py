# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .host_renderer import HostRenderer, HostUnavailableError
from .native_renderer import NativeRenderer


class UIAdapter:
	def __init__(self) -> None:
		self._native_renderer = NativeRenderer()
		self._host_renderer = HostRenderer()
		self._host_available = True

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
		if self._host_available:
			try:
				self._host_renderer.render_display_result(
					use_case_id=use_case_id,
					title=title,
					output_text=output_text,
					output_html=output_html,
					is_html=is_html,
					success=success,
					message=message,
					close_button=close_button,
					copy_button=copy_button,
					copy_text=copy_text,
					copy_html=copy_html,
					metadata=metadata,
				)
				return
			except HostUnavailableError:
				self._host_available = False

		self._native_renderer.render_display_result(
			use_case_id=use_case_id,
			title=title,
			output_text=output_text,
			output_html=output_html,
			is_html=is_html,
			success=success,
			message=message,
			close_button=close_button,
			copy_button=copy_button,
			copy_text=copy_text,
			copy_html=copy_html,
			metadata=metadata,
		)

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
		if self._host_available:
			try:
				self._host_renderer.open_chat(
					use_case_id=use_case_id,
					title=title,
					initial_text=initial_text,
					initial_image_base64=initial_image_base64,
					metadata=metadata,
				)
				return
			except HostUnavailableError:
				self._host_available = False

		self._native_renderer.open_chat(
			use_case_id=use_case_id,
			title=title,
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
			coordinator=coordinator,
			tool_registry=tool_registry,
			metadata=metadata,
		)

	def show_error(self, error_message: str, details: str | None = None) -> None:
		if self._host_available:
			try:
				self._host_renderer.show_error(error_message, details=details)
				return
			except HostUnavailableError:
				self._host_available = False

		self._native_renderer.show_error(error_message, details=details)

	def show_progress(self, message: str) -> None:
		if self._host_available:
			try:
				self._host_renderer.show_progress(message)
				return
			except HostUnavailableError:
				self._host_available = False

		self._native_renderer.show_progress(message)

	def close_window(self, reason: str | None = None) -> None:
		if self._host_available:
			try:
				self._host_renderer.close_window(reason)
				return
			except HostUnavailableError:
				self._host_available = False

		self._native_renderer.close_window(reason)


ui_adapter = UIAdapter()
