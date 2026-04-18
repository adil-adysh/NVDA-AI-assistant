# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable

import gui
from logHandler import log

from ..config.settings import get_provider_state
from ..config.state import ProviderState
from ..service.chat import ChatCoordinator
from ..tools import ToolRegistry
from .chat_ui import ChatDialog

_chat_dialog_instance: ChatDialog | None = None


def open_chat_dialog(
	coordinator: ChatCoordinator,
	tool_registry: ToolRegistry,
	initial_text: str | None = None,
	initial_image_base64: str | None = None,
) -> None:
	global _chat_dialog_instance
	provider_state = get_provider_state()
	if _chat_dialog_instance:
		try:
			_chat_dialog_instance.update_provider_state(provider_state)
			_chat_dialog_instance.Raise()
			_chat_dialog_instance.set_initial_state(initial_text, initial_image_base64)
		except Exception:
			log.exception("Error reusing chat dialog")
		return

	gui.mainFrame.prePopup()
	parent = getattr(gui, "mainFrame", None)
	_chat_dialog_instance = ChatDialog(
		parent,
		coordinator=coordinator,
		tool_registry=tool_registry,
		provider_state=provider_state,
		initial_text=initial_text,
		initial_image_base64=initial_image_base64,
		destroy_callback=_on_dialog_destroyed,
	)
	try:
		_chat_dialog_instance.Show()
	except Exception:
		_chat_dialog_instance = None
		raise
	finally:
		gui.mainFrame.postPopup()


def update_provider_state(provider_state: ProviderState | None = None) -> None:
	if provider_state is None:
		provider_state = get_provider_state()
	if _chat_dialog_instance:
		try:
			_chat_dialog_instance.update_provider_state(provider_state)
		except Exception:
			log.exception("Error updating chat dialog provider state")


def _on_dialog_destroyed(dialog: ChatDialog) -> None:
	global _chat_dialog_instance
	if _chat_dialog_instance is dialog:
		_chat_dialog_instance = None
