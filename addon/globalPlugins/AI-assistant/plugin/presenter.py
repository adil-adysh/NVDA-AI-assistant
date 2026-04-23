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
from ..ui.adapter import ui_adapter
from ..ui import chat_dialog_manager, nvda_ui


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
		ui_adapter.open_chat(
			title=_("AI Chat"),
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
			coordinator=self._chat_coordinator,
			tool_registry=self._tool_registry,
			metadata=None,
		)

	def update_provider_state(self, provider_state: ProviderState | None = None) -> None:
		try:
			if provider_state is None:
				provider_state = get_provider_state()
			chat_dialog_manager.update_provider_state(provider_state)
		except Exception:
			log.exception("Error updating chat dialog title after provider state changed")

	def present_use_case_result(self, use_case_result: Any, title: str) -> None:
		log.debug("UseCasePresenter.present_use_case_result called title=%s result_type=%s", title, type(use_case_result).__name__)
		output_text = None
		output_html = None
		is_html = False

		if isinstance(use_case_result, dict):
			output_text = use_case_result.get("output_text")
			output_html = use_case_result.get("output_html")
			is_html = bool(use_case_result.get("is_html"))
		else:
			metadata = getattr(use_case_result, "metadata", None)
			output_text = getattr(use_case_result, "output_text", None)
			output_html = getattr(use_case_result, "output_html", None)
			if output_html is None and isinstance(metadata, dict):
				output_text = output_text or metadata.get("output_text")
				is_html = bool(getattr(use_case_result, "is_browseable", False) or metadata.get("is_html"))
			else:
				is_html = bool(getattr(use_case_result, "is_browseable", False))

		if output_html is not None:
			output_text = output_html
			is_html = True

		if not isinstance(output_text, str) or not output_text.strip():
			error_message = getattr(use_case_result, "error_message", None)
			log.warning("UseCasePresenter received empty output_text; error_message=%s", error_message)
			if isinstance(error_message, str) and error_message.strip():
				nvda_ui.message(error_message)
				return
			nvda_ui.message(_("No result to display."))
			return

		browseable_title = nvda_ui.format_browseable_title(title, get_provider_state())
		use_case_id = None
		prompt_context = getattr(use_case_result, "prompt_context", None)
		if prompt_context is not None:
			use_case_id = getattr(prompt_context, "use_case_id", None)
		copy_text = output_text or output_html
		copy_html = output_html if is_html else None
		ui_adapter.render_display_result(
			use_case_id=use_case_id,
			title=browseable_title,
			output_text=output_text,
			output_html=output_html,
			is_html=is_html,
			success=True,
			message=getattr(use_case_result, "message", None),
			close_button=True,
			copy_button=True,
			copy_text=copy_text,
			copy_html=copy_html,
			metadata=getattr(use_case_result, "metadata", None),
		)

	def progress_handler(self, event: ProgressEvent) -> None:
		if event.stage == "error":
			nvda_ui.queue(nvda_ui.message, _("Error: ") + event.message)
			return

		if event.stage in {"start", "collecting_context", "building_prompt", "llm_request", "tool_execution", "complete"}:
			nvda_ui.queue(nvda_ui.message, event.message)
