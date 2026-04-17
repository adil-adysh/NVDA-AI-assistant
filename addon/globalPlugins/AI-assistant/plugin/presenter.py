# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

import gui
import markdown
from logHandler import log

from ..config.state import ProviderState
from ..core.events import ProgressEvent
from ..service.chat import ChatCoordinator
from ..tools import ToolRegistry
from ..config.settings import get_provider_state
from ..ui import chat_ui, nvda_ui


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
		if chat_ui.chatDialogInstance:
			try:
				chat_ui.chatDialogInstance.update_provider_state(get_provider_state())
				chat_ui.chatDialogInstance.Raise()
				chat_ui.chatDialogInstance.set_initial_state(initial_text, initial_image_base64)
			except Exception:
				log.exception("Error reusing chat dialog")
			return

		gui.mainFrame.prePopup()
		parent = getattr(gui, "mainFrame", None)
		chat_ui.chatDialogInstance = chat_ui.ChatDialog(
			parent,
			coordinator=self._chat_coordinator,
			tool_registry=self._tool_registry,
			provider_state=get_provider_state(),
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
		)
		try:
			chat_ui.chatDialogInstance.Show()
		except Exception:
			chat_ui.chatDialogInstance = None
			raise
		finally:
			gui.mainFrame.postPopup()

	def update_provider_state(self, provider_state: ProviderState | None = None) -> None:
		try:
			if provider_state is None:
				provider_state = get_provider_state()
			if chat_ui.chatDialogInstance:
				chat_ui.chatDialogInstance.update_provider_state(provider_state)
		except Exception:
			log.exception("Error updating chat dialog title after provider state changed")

	def present_use_case_result(self, use_case_result: Any, title: str) -> None:
		output_text = None
		output_format = None
		if isinstance(use_case_result, dict):
			output_text = use_case_result.get("output_text")
			output_format = use_case_result.get("output_format")
		else:
			output_format = getattr(use_case_result, "output_format", None)
			metadata = getattr(use_case_result, "metadata", None)
			if isinstance(metadata, dict):
				output_text = metadata.get("output_text")
				if output_format is None:
					output_format = metadata.get("output_format")

		if not isinstance(output_text, str) or not output_text.strip():
			nvda_ui.message(_("No result to display."))
			return

		browseable_title = nvda_ui.format_browseable_title(title, get_provider_state())
		if output_format == "markdown":
			try:
				output_text = markdown.markdown(
					output_text,
					output_format="html5",
					extensions=["extra", "smarty", "sane_lists"],
				)
			except Exception:
				log.exception("Error rendering markdown for use case result")
			nvda_ui.browseable_message(
				output_text,
				title=browseable_title,
				is_html=True,
				close_button=True,
				copy_button=True,
			)
			return

		is_html = output_format == "html"
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
