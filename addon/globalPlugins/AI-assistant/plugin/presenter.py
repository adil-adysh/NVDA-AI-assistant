# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

import gui
from logHandler import log

from ..config.state import ProviderState
from ..core.events import ProgressEvent
from ..service.chat import ChatCoordinator
from ..tools import ToolRegistry
from ..config.settings import get_provider_state
from ..ui import chat_dialog_manager, nvda_ui
from ..utils.mathml import contains_mathml


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class UseCasePresenter:
	def __init__(self, chat_coordinator: ChatCoordinator, tool_registry: ToolRegistry) -> None:
		self._chat_coordinator = chat_coordinator
		self._tool_registry = tool_registry

	def open_chat_window(
		self,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
	) -> None:
		chat_dialog_manager.open_chat_dialog(
			coordinator=self._chat_coordinator,
			tool_registry=self._tool_registry,
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
		)

	def update_provider_state(self, provider_state: ProviderState | None = None) -> None:
		try:
			if provider_state is None:
				provider_state = get_provider_state()
			chat_dialog_manager.update_provider_state(provider_state)
		except Exception:
			log.exception("Error updating chat dialog title after provider state changed")

	def present_use_case_result(self, use_case_result: Any, title: str) -> None:
		output_text = None
		is_html = False
		if isinstance(use_case_result, dict):
			output_text = use_case_result.get("output_text")
			is_html = bool(use_case_result.get("is_html"))
		else:
			metadata = getattr(use_case_result, "metadata", None)
			if isinstance(metadata, dict):
				output_text = metadata.get("output_text")
				is_html = bool(metadata.get("is_html"))

		if not isinstance(output_text, str) or not output_text.strip():
			nvda_ui.message(_("No result to display."))
			return

		browseable_title = nvda_ui.format_browseable_title(title, get_provider_state())
		if is_html and contains_mathml(output_text):
			nvda_ui.browseable_message(
				output_text,
				title=browseable_title,
				is_html=is_html,
				close_button=True,
				copy_button=True,
				sanitize_html_func=lambda html: html,
			)
		else:
			nvda_ui.browseable_message(
				output_text,
				title=browseable_title,
				is_html=is_html,
				close_button=True,
				copy_button=True,
			)

	def progress_handler(self, event: ProgressEvent) -> None:
		if event.stage == "error":
			nvda_ui.queue(nvda_ui.message, _("Error: ") + event.message)
			return

		if event.stage in {"start", "collecting_context", "building_prompt", "llm_request", "tool_execution", "complete"}:
			nvda_ui.queue(nvda_ui.message, event.message)
