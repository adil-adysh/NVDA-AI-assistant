# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from . import chat_dialog_manager, nvda_ui
from .host_interface import UIHostRenderer


class NativeRenderer(UIHostRenderer):
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
		if not success and message:
			nvda_ui.message(message)
			return

		if output_html is not None or output_text is not None:
			text = output_html if is_html and output_html is not None else output_text or ""
			nvda_ui.browseable_message(
				text,
				title=title,
				is_html=is_html,
				close_button=close_button,
				copy_button=copy_button,
			)
			return

		if message:
			nvda_ui.message(message)

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
		if coordinator is None or tool_registry is None:
			nvda_ui.message("Unable to open chat: missing chat coordinator or tool registry.")
			return

		chat_dialog_manager.open_chat_dialog(
			coordinator=coordinator,
			tool_registry=tool_registry,
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
		)

	def show_error(self, error_message: str, details: str | None = None) -> None:
		nvda_ui.message(error_message)

	def show_progress(self, message: str) -> None:
		nvda_ui.queue(nvda_ui.message, message)

	def close_window(self, reason: str | None = None) -> None:
		# Native UI does not have a dedicated close command.
		pass
