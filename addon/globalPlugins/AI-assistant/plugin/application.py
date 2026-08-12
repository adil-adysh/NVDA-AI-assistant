# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
from typing import Any, cast

import addonHandler
import gui
from logHandler import log

from ..config.state import ProviderState, subscribe_provider_state_change, unsubscribe_provider_state_change
from ..config.settings import get_enabled_providers, get_provider, get_provider_state
from ..context.extractors.selection import safe_extract_selection
from ..service import get_provider_display_name, provider_control_service
from ..service.model_cache import model_catalog_cache
from ..ui.host_process import stop_host
from ..ui.settings_panel import AIAssistantSettingsPanel
from ..ui import nvda_ui
from ..ui.session_state import build_provider_status_message
from ..utils.clipboard import safe_read_clipboard
from ..use_case.types import (
	ATTACH_FOCUSED_IMAGE_TO_CHAT,
	DESCRIBE_FOCUSED_IMAGE,
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
		self._auto_start_litert_if_active()
		self._last_provider_state = get_provider_state()
		self.presenter = UseCasePresenter(
			chat_coordinator=self._services.chat_coordinator,
			conversation_service=self._services.conversation_service,
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
				("f", host.script_describeFocusedObject),
				("c", host.script_openChatWindow),
				("p", host.script_openChatWithPageContent),
				("x", host.script_openChatWithScreenshot),
				("z", host.script_attachFocusedObjectToChat),
				("v", host.script_attachSelectionToChat),
				("b", host.script_attachClipboardToChat),
				("t", host.script_toggleAIProvider),			("m", host.script_selectModel),				("h", host.script_assistantLayerHelp),
			),
			bind_gesture=host.bindGesture,
			clear_gesture_bindings=host.clearGestureBindings,
			restore_default_gestures=host._restore_default_gesture_bindings,
		)
		subscribe_provider_state_change(self._on_provider_state_change)
		self._register_settings_panel()
		# Preload model catalog for all enabled providers in the background
		# so that the first "m" gesture or model manager dialog open is instant.
		try:
			model_catalog_cache.preload_all()
		except Exception:
			log.exception("Failed to start model catalog preload")
		log.debug("Browser Assistant plugin initialized")

	@property
	def services(self) -> PluginServices:
		return self._services

	def _auto_start_litert_if_active(self) -> None:
		"""Start the LiteRT-LM server in a background thread when it is the active provider.

		The check is cheap — only reads config and checks disk paths.
		Actual server startup (including the health/adopt probe for a
		server that survived an NVDA restart) runs on a daemon thread so
		NVDA startup is never delayed or blocked on socket I/O.
		"""
		try:
			if get_provider() != "litert-lm":
				return
			from ..providers.runtime.server import get_litert_supervisor
			supervisor = get_litert_supervisor()
			if not supervisor.is_installed:
				return
			# A live process handle means the server is already running.
			if supervisor.is_running:
				return

			# Delegate health/adopt/start to a daemon thread. The readiness
			# path adopts a healthy server whose handle was lost after an
			# NVDA restart, and starts one otherwise — without blocking here.
			from .background import ensure_litert_server_ready
			threading.Thread(
				target=ensure_litert_server_ready,
				name="LiteRTServerAutoStart",
				daemon=True,
			).start()
			log.debug("LiteRT server auto-start scheduled in background")
		except Exception:
			log.exception("Error during LiteRT server auto-start check")

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
		try:
			from ..providers.runtime.server import get_litert_supervisor
			# Process termination may wait for a slow/inference-busy server.
			# Never hold up NVDA shutdown on that wait.
			threading.Thread(
				target=get_litert_supervisor().stop,
				name="LiteRTServerShutdown",
				daemon=True,
			).start()
		except Exception:
			log.exception("Error stopping LiteRT server during terminate")
		self._unregister_settings_panel()

	def _on_provider_state_change(self, provider_state: ProviderState) -> None:
		"""Handle provider state changes off the main thread.

		The call chain includes synchronous IPC (``sync_session_state``
		via ``update_provider_state``) which can block for seconds while
		the host process starts or responds.  We must not block the
		NVDA main thread.
		"""
		threading.Thread(
			target=self._handle_provider_state_change,
			args=(provider_state,),
			name="ProviderStateChange",
			daemon=True,
		).start()

	def _handle_provider_state_change(self, provider_state: ProviderState) -> None:
		previous_state = self._last_provider_state
		self._last_provider_state = provider_state
		self.presenter.update_provider_state(provider_state)
		if provider_state != previous_state:
			self.background.start_model_preload()

	def run_summary(self) -> None:
		log.debug("AIAssistantApplication.run_summary called")
		self.background.run_use_case_in_background(
			SUMMARY,
			# TRANSLATORS: Title shown for the page summary result.
		title=_("Page summary"),
			# TRANSLATORS: Title shown for the page summary result.
			render_result=lambda result: self.presenter.present_use_case_result(result, title=_("Page summary")),
		)

	def run_structure_summary(self) -> None:
		log.debug("AIAssistantApplication.run_structure_summary called")
		self.background.run_use_case_in_background(
			STRUCTURE_SUMMARY,
			# TRANSLATORS: Title shown for the structure summary result.
		title=_("Structure summary"),
			# TRANSLATORS: Title shown for the structure summary result.
			render_result=lambda result: self.presenter.present_use_case_result(result, title=_("Structure summary")),
		)

	def describe_current_window(self) -> None:
		self.background.run_use_case_in_background(
			DESCRIBE_IMAGE,
			# TRANSLATORS: Title shown for the image description result.
		title=_("Image description"),
			# TRANSLATORS: Title shown for the image description result.
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
			# TRANSLATORS: Title shown for the AI chat window.
			title=_("AI Chat"),
			render_result=lambda result: self.open_chat_window(
				initial_text=result.initial_text,
				initial_image_base64=result.initial_image_base64,
			),
		)

	def open_chat_with_page_content(self) -> None:
		self.background.run_use_case_in_background(
			OPEN_CHAT_WITH_PAGE_CONTENT,
			# TRANSLATORS: Title shown for the AI chat window.
			title=_("AI Chat"),
			render_result=lambda result: self.open_chat_window(initial_text=result.initial_text),
		)

	def open_chat_with_screenshot(self) -> None:
		self.background.run_use_case_in_background(
			OPEN_CHAT_WITH_SCREENSHOT,
			# TRANSLATORS: Title shown for the AI chat window.
			title=_("AI Chat"),
			render_result=lambda result: self.open_chat_window(
				initial_text=result.initial_text,
				initial_image_base64=result.initial_image_base64,
			),
		)

	def describe_focused_object(self) -> None:
		self.background.run_use_case_in_background(
			DESCRIBE_FOCUSED_IMAGE,
			# TRANSLATORS: Title shown for the focused object image description result.
			title=_("Focused object description"),
			# TRANSLATORS: Title shown for the focused object image description result.
			render_result=lambda result: self.presenter.present_use_case_result(result, title=_("Focused object description")),
		)

	def attach_focused_object_to_chat(self) -> None:
		self.background.run_use_case_in_background(
			ATTACH_FOCUSED_IMAGE_TO_CHAT,
			# TRANSLATORS: Title shown for the AI chat window.
			title=_("AI Chat"),
			render_result=lambda result: self.open_chat_window(
				initial_text=result.initial_text,
				initial_image_base64=result.initial_image_base64,
			),
		)

	def attach_selection_to_chat(self) -> None:
		"""Extract selected text from the focused NVDA object and inject it into the current chat conversation."""
		selected_text = safe_extract_selection()
		if selected_text is None:
			# TRANSLATORS: Message spoken when nothing is selected in the current focus.
			nvda_ui.message(_("No text is currently selected."))
			return

		# TRANSLATORS: Message spoken when selected text is extracted and injected into chat.
		nvda_ui.message(_("Adding selected text to chat."))
		self.open_chat_window(
			initial_text=selected_text,
		)

	def attach_clipboard_to_chat(self) -> None:
		"""Read text from the system clipboard and inject it into the current chat conversation."""
		clipboard_text = safe_read_clipboard()
		if clipboard_text is None:
			# TRANSLATORS: Message spoken when the clipboard is empty or contains non-text content.
			nvda_ui.message(_("No text content found in clipboard."))
			return

		# TRANSLATORS: Message spoken when clipboard text is read and injected into chat.
		nvda_ui.message(_("Adding clipboard content to chat."))
		self.open_chat_window(
			initial_text=clipboard_text,
		)

	def activate_assistant_layer(self) -> None:
		self.layer_mode.activate()

	def toggle_provider(self) -> None:
		"""Announce enabled providers with digit labels and enter digit-selection mode."""
		enabled = get_enabled_providers()
		if not enabled:
			# TRANSLATORS: Message spoken when no AI providers are enabled.
			nvda_ui.message(_("No AI providers are enabled."))
			self.layer_mode.finish()
			return
		# Build announcement with digit labels.
		lines: list[str] = []
		for i, pid in enumerate(enabled):
			digit = (i + 1) % 10  # 1-9, 0 for 10th
			label = get_provider_display_name(pid)
			lines.append(f"{digit}: {label}")
		nvda_ui.message("\n".join(lines))
		# Enter digit-selection mode.
		def _on_provider_digit(digit: int) -> None:
			idx = (digit - 1) if digit != 0 else 9
			if idx < len(enabled):
				self._select_provider_by_id(enabled[idx])
		self.layer_mode.enter_digit_selection(_on_provider_digit)

	def _select_provider_by_id(self, provider_id: str) -> None:
		"""Activate a provider by ID and announce the result."""
		try:
			result = provider_control_service.select_provider(provider_id)
		except Exception as error:
			from ..service.error_presentation import present_error
			nvda_ui.message(present_error(error, _).message)
			return
		provider_label = get_provider_display_name(result.provider_state.provider)
		# TRANSLATORS: Message spoken when the AI provider is switched.
		message = _("AI provider switched to {provider}.").format(provider=provider_label)
		guidance = build_provider_status_message(_, result.readiness)
		if guidance:
			message = f"{message} {guidance}"
		nvda_ui.message(message)

	def select_model_for_current_provider(self) -> None:
		"""Fetch enabled models from cache on a background thread, then announce digit labels.

		Model lists are served from the central ``ModelCatalogCache`` which is
		preloaded at startup.  A cache miss will trigger a synchronous network
		fetch on the background thread — the NVDA main thread is never blocked.
		"""
		layer = self.layer_mode

		def _fetch_and_announce() -> None:
			try:
				provider_id = get_provider()
				models = provider_control_service.list_enabled_models(provider_id)
			except Exception:
				log.exception("Failed to list models")
				def _announce_error() -> None:
					# TRANSLATORS: Message spoken when model listing fails.
					nvda_ui.message(_("Could not list models for the current provider."))
					layer.finish()
				nvda_ui.call(_announce_error)
				return
			if not models:
				def _announce_empty() -> None:
					# TRANSLATORS: Message spoken when the current provider has no enabled models.
					nvda_ui.message(_("No enabled models for the current provider."))
					layer.finish()
				nvda_ui.call(_announce_empty)
				return
			def _announce_and_prompt() -> None:
				lines: list[str] = []
				for i, m in enumerate(models):
					digit = (i + 1) % 10
					label = m.display_name or m.id
					lines.append(f"{digit}: {label}")
				nvda_ui.message("\n".join(lines))
				def _on_model_digit(digit: int) -> None:
					idx = (digit - 1) if digit != 0 else 9
					if idx < len(models):
						self._select_model_by_id(models[idx].id)
				layer.enter_digit_selection(_on_model_digit)
			nvda_ui.call(_announce_and_prompt)

		threading.Thread(
			target=_fetch_and_announce,
			name="ModelListFetch",
			daemon=True,
		).start()

	def _select_model_by_id(self, model_id: str) -> None:
		"""Activate a model by ID and announce the result.

		Uses ``ProviderControlService.select_model`` which returns a
		``ModelSwitchResult`` with pre-resolved display names — the
		gesture layer no longer performs its own model info lookups.
		"""
		try:
			result = provider_control_service.select_model(model_id)
		except Exception as error:
			from ..service.error_presentation import present_error
			nvda_ui.message(present_error(error, _).message)
			return
		# TRANSLATORS: Message spoken when the AI model is switched.
		message = _("Model switched to {model} on {provider}.").format(
			model=result.model_display_name,
			provider=result.provider_display_name,
		)
		nvda_ui.message(message)

	def show_assistant_layer_help(self) -> None:
		nvda_ui.message(
			# TRANSLATORS: Help message listing all available AI assistant layer commands.
			_(
				"Assistant layer commands: S for summary, O for structure summary, I for window image describe, F for focused object describe, C for chat, P for page content, X for screenshot, Z for attach focused object to chat, V for attach selection to chat, B for attach clipboard to chat, T for provider select, M for model select, H for help. Press the key after activating the layer with NVDA+Shift+A."
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
