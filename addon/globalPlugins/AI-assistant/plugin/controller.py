# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

import globalPluginHandler
import gui
import wx
from logHandler import log
from scriptHandler import script

from .application import AIAssistantApplication


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	# TRANSLATORS: Category name for AI assistant scripts shown in NVDA's input gestures dialog.
	scriptCategory = _("AI assistant")

	def __init__(self) -> None:
		super().__init__()
		self._app = AIAssistantApplication(self)
		self._tools_menu = gui.mainFrame.sysTrayIcon.toolsMenu
		self._build_tools_submenu()

	def _build_tools_submenu(self) -> None:
		"""Create the AI Assistant submenu under NVDA's Tools menu."""
		self._submenu = wx.Menu()
		# TRANSLATORS: Name of the menu item to open the AI provider management dialog.
		self._providers_item = self._submenu.Append(
			wx.ID_ANY, _("&Manage AI Providers..."),
		)
		# TRANSLATORS: Name of the submenu in NVDA's Tools menu for AI Assistant features.
		self._submenu_parent_item = self._tools_menu.AppendSubMenu(
			self._submenu, _("AI Assistant"),
		)
		gui.mainFrame.sysTrayIcon.Bind(
			wx.EVT_MENU, self._on_tools_manage_providers, self._providers_item,
		)

	def _restore_default_gesture_bindings(self) -> None:
		self.bindGestures(self.__gestures)

	def _on_tools_manage_providers(self, _event: wx.CommandEvent) -> None:
		"""Open the AI provider management dialog."""
		from ..ui.provider_dialog import open_provider_dialog
		gui.mainFrame.prePopup()
		open_provider_dialog(gui.mainFrame)
		gui.mainFrame.postPopup()

	def terminate(self) -> None:
		try:
			if hasattr(self, "_submenu_parent_item"):
				self._tools_menu.Remove(self._submenu_parent_item)
		except Exception:
			log.exception("Error removing AI Assistant submenu")
		try:
			self._app.terminate()
		except Exception:
			log.exception("Error terminating AI assistant application")
		super().terminate()

	@script(
		# TRANSLATORS: Description for the script that summarizes the current page using an AI provider.
		description=_("Summarizes the current page using the selected AI provider."),
	)
	def script_summarizeCurrentPage(self, gesture: Any):
		log.debug("Script summarizeCurrentPage invoked gesture=%s", gesture)
		self._app.run_summary()

	@script(
		# TRANSLATORS: Description for the script that summarizes page structure, including headings, links, and interactive elements.
		description=_("Summarizes page structure, including headings, links, and interactive elements."),
	)
	def script_summarizePageStructure(self, gesture: Any):
		log.debug("Script summarizePageStructure invoked gesture=%s", gesture)
		self._app.run_structure_summary()

	@script(
		# TRANSLATORS: Description for the script that describes the current foreground window using an AI provider.
		description=_("Captures and describes the current foreground window using the selected AI provider."),
	)
	def script_describeCurrentWindow(self, gesture: Any):
		log.debug("Script describeCurrentWindow invoked gesture=%s", gesture)
		self._app.describe_current_window()

	@script(
		# TRANSLATORS: Description for the script that opens the AI chat window.
		description=_("Opens the AI chat window."),
	)
	def script_openChatWindow(self, gesture: Any):
		log.debug("Script openChatWindow invoked gesture=%s", gesture)
		self._app.open_chat()

	@script(
		# TRANSLATORS: Description for the script that opens the AI chat window with the current page content preloaded.
		description=_("Opens the AI chat window with current page content preloaded."),
	)
	def script_openChatWithPageContent(self, gesture: Any):
		log.debug("Script openChatWithPageContent invoked gesture=%s", gesture)
		self._app.open_chat_with_page_content()

	@script(
		# TRANSLATORS: Description for the script that opens the AI chat window with a screenshot attached.
		description=_("Opens the AI chat window with a screenshot attached."),
	)
	def script_openChatWithScreenshot(self, gesture: Any):
		log.debug("Script openChatWithScreenshot invoked gesture=%s", gesture)
		self._app.open_chat_with_screenshot()

	@script(
		# TRANSLATORS: Description for the script that activates the AI assistant command layer.
		description=_(
			"Activate the AI assistant command layer. "
			"Press S for summary, O for structure summary, I for window image describe, F for focused object describe, C for chat, P for page content, X for screenshot, Z for attach focused object, V for attach selection, B for attach clipboard, H for help."
		),
		gesture="kb:NVDA+Shift+A",
	)
	def script_assistantLayerCommands(self, gesture: Any):
		log.debug("Script assistantLayerCommands invoked gesture=%s", gesture)
		if self._app.layer_mode.active:
			self.script_error(gesture)
			return
		self._app.activate_assistant_layer()

	@script(
		# TRANSLATORS: Description for the script that toggles the active AI provider.
		description=_("Toggles the active AI provider."),
	)
	def script_toggleAIProvider(self, gesture: Any):
		log.debug("Script toggleAIProvider invoked gesture=%s", gesture)
		self._app.toggle_provider()

	@script(
		# TRANSLATORS: Description for the script that lists available AI assistant layer commands.
		description=_("Lists available AI assistant layer commands."),
	)
	def script_assistantLayerHelp(self, _gesture: Any):
		self._app.show_assistant_layer_help()

	@script(
		# TRANSLATORS: Description for the script that captures and describes the currently focused NVDA object.
		description=_("Captures and describes the currently focused NVDA object using the selected AI provider."),
	)
	def script_describeFocusedObject(self, gesture: Any):
		log.debug("Script describeFocusedObject invoked gesture=%s", gesture)
		self._app.describe_focused_object()

	@script(
		# TRANSLATORS: Description for the script that opens the AI chat with the focused NVDA object image attached.
		description=_("Opens the AI chat window with the focused NVDA object image attached."),
	)
	def script_attachFocusedObjectToChat(self, gesture: Any):
		log.debug("Script attachFocusedObjectToChat invoked gesture=%s", gesture)
		self._app.attach_focused_object_to_chat()

	@script(
		# TRANSLATORS: Description for the script that adds the currently selected text to the chat conversation.
		description=_("Adds the currently selected text to the current chat conversation."),
	)
	def script_attachSelectionToChat(self, gesture: Any):
		log.debug("Script attachSelectionToChat invoked gesture=%s", gesture)
		self._app.attach_selection_to_chat()

	@script(
		# TRANSLATORS: Description for the script that adds clipboard content to the chat conversation.
		description=_("Adds text from the system clipboard to the current chat conversation."),
	)
	def script_attachClipboardToChat(self, gesture: Any):
		log.debug("Script attachClipboardToChat invoked gesture=%s", gesture)
		self._app.attach_clipboard_to_chat()

	def getScript(self, gesture: Any):
		if not self._app.layer_mode.active:
			return globalPluginHandler.GlobalPlugin.getScript(self, gesture)
		layer_script = self._app.layer_mode.resolve_script(gesture)
		if layer_script is None:
			return self.script_error
		return layer_script

	def runAndFinish(self, gesture: Any):
		self._app.layer_mode.run_and_finish(gesture)

	def finish(self) -> None:
		self._app.layer_mode.finish()

	def script_error(self, gesture: Any):
		self._app.layer_mode.script_error(gesture)
