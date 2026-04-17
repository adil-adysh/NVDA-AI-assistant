# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

import globalPluginHandler
from logHandler import log
from scriptHandler import script

from .application import AIAssistantApplication


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = _("Smart Browser Tools")

	def __init__(self) -> None:
		super().__init__()
		self._app = AIAssistantApplication(self)

	def _restore_default_gesture_bindings(self) -> None:
		self.bindGestures(self.__gestures)

	def terminate(self) -> None:
		try:
			self._app.terminate()
		except Exception:
			log.exception("Error terminating AI assistant application")
		super().terminate()

	@script(
		description=_("Summarizes the current page using the selected AI provider."),
	)
	def script_summarizeCurrentPage(self, gesture: Any):
		log.debug("Script summarizeCurrentPage invoked gesture=%s", gesture)
		self._app.run_summary()

	@script(
		description=_("Captures and describes the current foreground window using the selected AI provider."),
	)
	def script_describeCurrentWindow(self, gesture: Any):
		log.debug("Script describeCurrentWindow invoked gesture=%s", gesture)
		self._app.describe_current_window()

	@script(
		description=_("Opens the AI chat window."),
	)
	def script_openChatWindow(self, gesture: Any):
		log.debug("Script openChatWindow invoked gesture=%s", gesture)
		self._app.open_chat()

	@script(
		description=_("Opens the AI chat window with current page content preloaded."),
	)
	def script_openChatWithPageContent(self, gesture: Any):
		log.debug("Script openChatWithPageContent invoked gesture=%s", gesture)
		self._app.open_chat_with_page_content()

	@script(
		description=_("Opens the AI chat window with a screenshot attached."),
	)
	def script_openChatWithScreenshot(self, gesture: Any):
		log.debug("Script openChatWithScreenshot invoked gesture=%s", gesture)
		self._app.open_chat_with_screenshot()

	@script(
		description=_(
			"Activate the AI assistant command layer. "
			"Press S for summary, I for image describe, C for chat, P for page content, X for screenshot, U for custom use cases, T for provider toggle, H for help."
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
		description=_("Lists available custom AI use cases."),
	)
	def script_listCustomUseCases(self, gesture: Any):
		log.debug("Script listCustomUseCases invoked gesture=%s", gesture)
		self._app.layer_mode.sustain()
		self._app.list_custom_use_cases()

	@script(
		description=_("Activates a custom AI use case by pressing a number key while the assistant layer is active."),
	)
	def script_activateCustomUseCase(self, gesture: Any):
		main_key = getattr(gesture, "mainKeyName", "")
		log.debug("Script activateCustomUseCase invoked gesture=%s key=%s", gesture, main_key)
		self._app.activate_custom_use_case_by_key(str(main_key))

	@script(
		description=_("Toggles the active AI provider between Ollama and Gemini."),
	)
	def script_toggleAIProvider(self, gesture: Any):
		log.debug("Script toggleAIProvider invoked gesture=%s", gesture)
		self._app.toggle_provider()

	@script(
		description=_("Lists available AI assistant layer commands."),
	)
	def script_assistantLayerHelp(self, gesture: Any):
		self._app.show_assistant_layer_help()

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
