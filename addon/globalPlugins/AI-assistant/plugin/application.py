# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

import addonHandler
import gui
from logHandler import log

from ..config.state import ProviderState, subscribe_provider_state_change, unsubscribe_provider_state_change
from ..config.settings import get_provider_state
from ..service import get_provider_display_name, provider_control_service
from ..ui.host_process import stop_host
from ..ui.settings_panel import AIAssistantSettingsPanel
from ..ui import nvda_ui
from ..ui.session_state import build_provider_status_message
from ..use_case.types import (
	DESCRIBE_IMAGE,
	OPEN_CHAT,
	OPEN_CHAT_WITH_PAGE_CONTENT,
	OPEN_CHAT_WITH_SCREENSHOT,
	STRUCTURE_SUMMARY,
	SUMMARY,
)
from .background import BackgroundTaskRunner
from .factory import build_plugin_services
from .layer_mode import AssistantLayerController
from .presenter import UseCasePresenter
from .types import PluginServices


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class AIAssistantApplication:
	def __init__(self, host: Any) -> None:
		super().__init__()
		addonHandler.initTranslation()
		log.debug("Browser Assistant plugin initializing")
		self._host = host
		self._services = build_plugin_services()
		self._last_provider_state = get_provider_state()
		self.presenter = UseCasePresenter(
			chat_coordinator=self._services.chat_coordinator,
			tool_registry=self._services.tool_registry,
		)
		self.background = BackgroundTaskRunner(
			llm_service=self._services.llm_service,
			use_case_engine=self._services.use_case_engine,
			progress_handler=self.presenter.progress_handler,
		)
		self.layer_mode = AssistantLayerController(
			bindings=(
				("s", host.script_summarizeCurrentPage),
				("o", host.script_summarizePageStructure),
				("i", host.script_describeCurrentWindow),
				("c", host.script_openChatWindow),
				("p", host.script_openChatWithPageContent),
				("x", host.script_openChatWithScreenshot),
				("t", host.script_toggleAIProvider),
				("h", host.script_assistantLayerHelp),
			),
			bind_gesture=host.bindGesture,
			clear_gesture_bindings=host.clearGestureBindings,
			restore_default_gestures=host._restore_default_gesture_bindings,
		)
		subscribe_provider_state_change(self._on_provider_state_change)
		self._register_settings_panel()
		log.debug("Browser Assistant plugin initialized")

	@property
	def services(self) -> PluginServices:
		return self._services

	def terminate(self) -> None:
		try:
			self.presenter.close()
		except Exception:
			log.exception("Error closing presenter during terminate")
		try:
			unsubscribe_provider_state_change(self._on_provider_state_change)
		except Exception:
			log.exception("Error unsubscribing provider state listener")
		try:
			self._services.provider.close()
		except Exception:
			log.exception("Error closing provider during terminate")
		try:
			stop_host()
		except Exception:
			log.exception("Error stopping UI host during terminate")
		self._unregister_settings_panel()

	def _on_provider_state_change(self, provider_state: ProviderState) -> None:
		previous_state = self._last_provider_state
		self._last_provider_state = provider_state
		self.presenter.update_provider_state(provider_state)
		if provider_state != previous_state:
			self.background.start_model_preload()

	def run_summary(self) -> None:
		log.debug("AIAssistantApplication.run_summary called")
		self.background.run_use_case_in_background(
			SUMMARY,
			title=_("Page summary"),
			render_result=lambda result: self.presenter.present_use_case_result(result, title=_("Page summary")),
		)

	def run_structure_summary(self) -> None:
		log.debug("AIAssistantApplication.run_structure_summary called")
		self.background.run_use_case_in_background(
			STRUCTURE_SUMMARY,
			title=_("Structure summary"),
			render_result=lambda result: self.presenter.present_use_case_result(result, title=_("Structure summary")),
		)

	def describe_current_window(self) -> None:
		self.background.run_use_case_in_background(
			DESCRIBE_IMAGE,
			title=_("Image description"),
			render_result=lambda result: self.presenter.present_use_case_result(result, title=_("Image description")),
		)

	def open_chat_window(
		self,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
	) -> None:
		self.presenter.open_chat_window(
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
		)

	def open_chat(self) -> None:
		self.background.run_use_case_in_background(
			OPEN_CHAT,
			title=_("AI Chat"),
			render_result=lambda result: self.open_chat_window(
				initial_text=result.initial_text,
				initial_image_base64=result.initial_image_base64,
			),
		)

	def open_chat_with_page_content(self) -> None:
		self.background.run_use_case_in_background(
			OPEN_CHAT_WITH_PAGE_CONTENT,
			title=_("AI Chat"),
			render_result=lambda result: self.open_chat_window(initial_text=result.initial_text),
		)

	def open_chat_with_screenshot(self) -> None:
		self.background.run_use_case_in_background(
			OPEN_CHAT_WITH_SCREENSHOT,
			title=_("AI Chat"),
			render_result=lambda result: self.open_chat_window(
				initial_text=result.initial_text,
				initial_image_base64=result.initial_image_base64,
			),
		)

	def activate_assistant_layer(self) -> None:
		self.layer_mode.activate()

	def toggle_provider(self) -> None:
		try:
			result = provider_control_service.cycle_provider()
		except Exception as error:
			nvda_ui.message(str(error))
			return

		provider_label = get_provider_display_name(result.provider_state.provider)
		message = _("AI provider switched to {provider}.").format(provider=provider_label)
		guidance = build_provider_status_message(_, result.readiness)
		if guidance:
			message = f"{message} {guidance}"
		nvda_ui.message(message)

	def show_assistant_layer_help(self) -> None:
		nvda_ui.message(
			_(
				"Assistant layer commands: S for summary, O for structure summary, I for image describe, C for chat, P for page content, X for screenshot, T for provider toggle, H for help. Press the key after activating the layer with NVDA+Shift+A."
			)
		)

	def on_provider_state_changed(self, provider_state: ProviderState) -> None:
		self.presenter.update_provider_state(provider_state)

	def _register_settings_panel(self) -> None:
		category_classes = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
		if AIAssistantSettingsPanel not in category_classes:
			category_classes.append(AIAssistantSettingsPanel)

	def _unregister_settings_panel(self) -> None:
		category_classes = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
		if AIAssistantSettingsPanel in category_classes:
			category_classes.remove(AIAssistantSettingsPanel)
