# -*- coding: utf-8 -*-
"""AI Assistant settings dialog and its accessible tab panels."""
from __future__ import annotations

import builtins
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

import addonHandler
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsDialog
from wx.lib import scrolledpanel

from ..config import defaults
from ..config.settings import (
	build_provider_config, get_enabled_providers, get_embedding_enabled, get_embedding_model,
	get_embedding_page_chat_enabled, get_embedding_page_summary_enabled, get_generate_max_tokens,
	get_generate_temperature, get_generate_top_p, get_image_format, get_image_max_side, get_image_quality,
	get_language, get_local_startup_mode, LOCAL_STARTUP_MODES, get_num_ctx, get_progress_enabled,
	get_provider, get_request_metrics_log_path, get_request_metrics_logging_enabled, get_streaming_enabled,
	get_streaming_tone_enabled, get_timeout_seconds, set_embedding_enabled, set_embedding_model,
	set_embedding_page_chat_enabled, set_embedding_page_summary_enabled, set_generate_max_tokens,
	set_generate_temperature, set_generate_top_p, set_image_format, set_image_max_side, set_image_quality,
	set_language, set_local_startup_mode, set_model_name, set_num_ctx,
	set_progress_enabled, set_provider, set_request_metrics_log_path, set_request_metrics_logging_enabled,
	set_streaming_enabled, set_streaming_tone_enabled, set_timeout_seconds,
	get_one_shot_output_mode, set_one_shot_output_mode, ONE_SHOT_OUTPUT_MODES,
	get_chat_auto_read, set_chat_auto_read, get_chat_status_announcements, set_chat_status_announcements,
)
from ..config.enabled_models import ModelVisibilityStore
from ..embeddings.manager import embedding_model_service
from ..providers.registry import (
	PROVIDER_IDS, ProviderLifecycleState, build_model_manager, get_provider_info,
	provider_display_name, provider_state_label,
)
from ..service.model_cache import model_capability_cache, model_catalog_cache
from .task_runner import TaskHandle, background_tasks
from .mcp_settings import McpSettingsPanel

addonHandler.initTranslation()
_ = cast(Callable[[str], str], getattr(builtins, "_", lambda value: value))


@dataclass(frozen=True)
class _SettingsValues:
	provider: str
	model_name: str
	num_ctx: int
	temperature: float
	top_p: float
	max_tokens: int
	embedding_enabled: bool
	embedding_summary: bool
	embedding_page_chat: bool
	embedding_model: str
	streaming: bool
	progress: bool
	streaming_tone: bool
	one_shot_output_mode: str
	chat_auto_read: bool
	chat_status_announcements: bool
	language: str
	image_max_side: int
	image_format: str
	image_quality: int
	timeout_seconds: float
	litert_startup: str
	llama_startup: str
	metrics_enabled: bool
	metrics_path: str


class _InvalidSetting(ValueError):
	def __init__(self, message: str, control: wx.Window, tab: wx.Window):
		super().__init__(message)
		self.control = control
		self.tab = tab


class _SettingsTab(scrolledpanel.ScrolledPanel):
	"""Common accessible, scrollable tab implementation."""

	def __init__(self, parent: wx.Window, dialog: "AIAssistantSettingsDialog") -> None:
		scrolledpanel.ScrolledPanel.__init__(self, parent, style=wx.TAB_TRAVERSAL)
		self.dialog = dialog
		self._helper = guiHelper.BoxSizerHelper(self, wx.VERTICAL)
		self.SetSizer(self._helper.sizer)
		self.SetupScrolling(scroll_x=False)

	def add_group(self, title: str) -> guiHelper.BoxSizerHelper:
		helper = guiHelper.BoxSizerHelper(self, sizer=wx.StaticBoxSizer(wx.VERTICAL, self, label=title))
		self._helper.addItem(helper)
		return helper

	def add_labeled_text(self, helper: guiHelper.BoxSizerHelper, label: str, value: object) -> wx.TextCtrl:
		helper.addItem(wx.StaticText(self, label=label))
		control = wx.TextCtrl(self, value=str(value))
		control.SetName(label)
		helper.addItem(control)
		return control

	def add_labeled_combo(self, helper: guiHelper.BoxSizerHelper, label: str, choices: list[str], selection: str) -> wx.ComboBox:
		helper.addItem(wx.StaticText(self, label=label))
		control = wx.ComboBox(self, choices=choices, style=wx.CB_READONLY)
		control.SetName(label)
		if selection in choices:
			control.SetStringSelection(selection)
		elif choices:
			control.SetSelection(0)
		helper.addItem(control)
		return control

	def parse_int(self, control: wx.TextCtrl, message: str, minimum: int) -> int:
		try:
			value = int(control.GetValue().strip())
		except ValueError as error:
			raise _InvalidSetting(message, control, self) from error
		if value < minimum:
			raise _InvalidSetting(message, control, self)
		return value

	def parse_float(self, control: wx.TextCtrl, message: str, minimum: float, maximum: float | None = None) -> float:
		try:
			value = float(control.GetValue().strip())
		except ValueError as error:
			raise _InvalidSetting(message, control, self) from error
		if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
			raise _InvalidSetting(message, control, self)
		return value

	def collect(self, values: dict[str, object]) -> None:
		return


class ModelChoiceList(list):
	"""Rendered choices with exact IDs, delivered as one generation-fenced result."""
	def __init__(self):
		super().__init__()
		self.identities = {}
		self.selectable = set()


class AIAssistantGeneralPanel(_SettingsTab):
	title = _("General")

	def __init__(self, parent: wx.Window, dialog: "AIAssistantSettingsDialog") -> None:
		super().__init__(parent, dialog)
		helper = self.add_group(_("Active AI"))
		helper.addItem(wx.StaticText(self, label=_("Active provider:")))
		self.provider_choice = helper.addItem(wx.Choice(self, choices=[provider_display_name(pid) for pid in PROVIDER_IDS]))
		self.provider_choice.SetSelection(self._selected_provider_index(get_provider()))
		self.provider_status = helper.addItem(wx.StaticText(self, label=""))
		helper.addItem(wx.StaticText(self, label=_("Active model:")))
		self.model_combo = helper.addItem(wx.ComboBox(self, choices=[], style=wx.CB_DROPDOWN))
		self.manage_providers = helper.addItem(wx.Button(self, label=_("&Manage AI Providers...")))
		self.configure_model = helper.addItem(wx.Button(self, label=_("Configure Active &Model...")))
		helper.addItem(wx.StaticText(self, label=_("Per-model generation settings are configured from Manage AI Providers or Configure Active Model.")))
		self.provider_choice.Bind(wx.EVT_CHOICE, self._on_provider_choice)
		self.manage_providers.Bind(wx.EVT_BUTTON, self._on_manage_providers)
		self.configure_model.Bind(wx.EVT_BUTTON, self._on_configure_model)
		self._model_choice_task: TaskHandle[list[str]] | None = None
		self._model_choice_generation = 0
		self._model_choice_provider: str | None = None
		self._model_drafts: dict[str, str] = {}
		self._update_active_state()

	def _selected_provider_index(self, provider: str) -> int:
		return PROVIDER_IDS.index(provider) if provider in PROVIDER_IDS else 0

	def selected_provider(self) -> str:
		index = self.provider_choice.GetSelection()
		return PROVIDER_IDS[index] if 0 <= index < len(PROVIDER_IDS) else get_provider()

	def _current_model_name(self, provider_id: str) -> str:
		try:
			return str(build_provider_config(provider_id).model_name or "").strip()
		except Exception:
			return ""

	def _model_choices_for(self, provider_id: str) -> list[str]:
		choices = ModelChoiceList()
		try:
			manager = build_model_manager(provider_id, model_cache=model_catalog_cache, capability_cache=model_capability_cache)
			from ..providers.model_manager import ModelAction, available_model_actions
			for model in manager.list_managed_models():
				if ModelAction.SELECT not in available_model_actions(model, manager.features):
					continue
				label = model.id if model.display_name == model.id else _("{name} [{id}]").format(name=model.display_name, id=model.id)
				choices.append(label)
				choices.identities[label] = model.id
				choices.identities[model.id] = model.id
				choices.selectable.add(model.id)
		except Exception:
			pass
		if not choices and provider_id != "llama-cpp-server":
			try:
				for model in model_catalog_cache.get_models_or_empty(provider_id):
					choices.append(model.id)
					choices.identities[model.id] = model.id
					choices.selectable.add(model.id)
			except Exception:
				pass
		try:
			visibility = ModelVisibilityStore()
			choices[:] = [label for label in choices if visibility.is_model_visible(provider_id, choices.identities.get(label, label))]
		except Exception:
			pass
		current = self._current_model_name(provider_id)
		if current and current not in choices.selectable:
			label = _("Unavailable: {model}").format(model=current)
			choices.insert(0, label)
			choices.identities[label] = current
		return choices

	def _refresh_model_choices(self, provider_id: str) -> None:
		if self._model_choice_task is not None:
			self._model_choice_task.cancel()
		if self._model_choice_provider is not None:
			self._model_drafts[self._model_choice_provider] = self.model_combo.GetValue()
		self._model_choice_provider = provider_id
		self._model_choice_generation += 1
		generation = self._model_choice_generation
		self.model_combo.Clear()
		self.model_combo.SetValue(self._model_drafts.get(provider_id, self._current_model_name(provider_id)))
		self._model_choice_task = background_tasks.submit(
			lambda _cancel: self._model_choices_for(provider_id),
			on_success=lambda choices: self._apply_model_choices(provider_id, choices, generation),
			is_alive=lambda: bool(self) and not self.IsBeingDeleted(),
		)

	def _apply_model_choices(self, provider_id: str, choices: list[str], generation: int) -> None:
		if not bool(self) or self.IsBeingDeleted() or provider_id != self.selected_provider() or generation != self._model_choice_generation:
			return
		draft = self.model_combo.GetValue()
		self._model_choice_identity = getattr(choices, "identities", {})
		self._model_choice_selectable = getattr(choices, "selectable", set(choices))
		self.model_combo.Clear()
		self.model_combo.AppendItems(choices)
		if draft == self._current_model_name(provider_id):
			draft = next((label for label in choices if self._model_choice_identity.get(label) == draft), draft)
		self.model_combo.SetValue(draft)
		self.model_combo.Enable()

	def _refresh_status(self, provider_id: str) -> None:
		info = get_provider_info(provider_id)
		state = provider_state_label(info.state)
		if not info.enabled:
			message = _("Status: {state}. This provider is disabled. Use Manage AI Providers to enable it.")
		elif info.state is ProviderLifecycleState.NOT_INSTALLED:
			message = _("Status: {state}. Use Manage AI Providers to install this provider.")
		elif info.state is ProviderLifecycleState.AVAILABLE:
			message = _("Status: {state}. Use Manage AI Providers to configure this provider.")
		else:
			message = _("Status: {state}.")
		self.provider_status.SetLabel(message.format(state=state))

	def _update_active_state(self) -> None:
		provider_id = self.selected_provider()
		self._refresh_model_choices(provider_id)
		self._refresh_status(provider_id)
		self.Layout()

	def _on_provider_choice(self, _event: wx.CommandEvent) -> None:
		self._update_active_state()

	def _on_manage_providers(self, _event: wx.CommandEvent) -> None:
		from .provider_dialog import open_provider_dialog
		open_provider_dialog(self.dialog)
		if self.selected_provider() not in get_enabled_providers():
			self.provider_choice.SetSelection(self._selected_provider_index(get_provider()))
		self._update_active_state()

	def _on_configure_model(self, _event: wx.CommandEvent) -> None:
		model_name = getattr(self, "_model_choice_identity", {}).get(self.model_combo.GetValue().strip(), self.model_combo.GetValue().strip())
		if not model_name:
			self.dialog.show_validation_error(_("Select a model to configure first."), self.model_combo, self)
			return
		from .model_config_dialog import open_model_configure
		open_model_configure(self.dialog, self.selected_provider(), model_name, model_name)

	def collect(self, values: dict[str, object]) -> None:
		provider_id = self.selected_provider()
		if provider_id not in get_enabled_providers():
			raise _InvalidSetting(_("{name} is disabled. Enable it in Manage AI Providers first.").format(name=provider_display_name(provider_id)), self.provider_choice, self)
		model_name = getattr(self, "_model_choice_identity", {}).get(self.model_combo.GetValue().strip(), self.model_combo.GetValue().strip())
		if not model_name:
			raise _InvalidSetting(_("Active model name cannot be empty."), self.model_combo, self)
		if provider_id == "llama-cpp-server" and model_name not in getattr(self, "_model_choice_selectable", set()) and model_name != self._current_model_name(provider_id):
			raise _InvalidSetting(_("Choose an available configuration or create one in Manage Models."), self.model_combo, self)
		try:
			manager = build_model_manager(provider_id, model_cache=model_catalog_cache, capability_cache=model_capability_cache)
			model_name = manager.resolve_model_identity(model_name)
		except Exception:
			pass
		values.update(provider=provider_id, model_name=model_name)


class AIAssistantModelsContextPanel(_SettingsTab):
	title = _("Models & Context")

	def __init__(self, parent: wx.Window, dialog: "AIAssistantSettingsDialog") -> None:
		super().__init__(parent, dialog)
		helper = self.add_group(_("Model Defaults"))
		helper.addItem(wx.StaticText(self, label=_("Global generation parameters used by models without per-model overrides.")))
		self.num_ctx = self.add_labeled_text(helper, _("Context window size:"), get_num_ctx() or defaults.DEFAULT_NUM_CTX)
		self.temperature = self.add_labeled_text(helper, _("Temperature:"), get_generate_temperature())
		self.top_p = self.add_labeled_text(helper, _("Top-p:"), get_generate_top_p())
		self.max_tokens = self.add_labeled_text(helper, _("Max tokens:"), get_generate_max_tokens())
		helper = self.add_group(_("Context and memory"))
		helper.addItem(wx.StaticText(self, label=_("Local embedding models select relevant content before it is sent to the AI.")))
		self.embedding_enabled = helper.addItem(wx.CheckBox(self, label=_("Enable local context reduction")))
		self.embedding_enabled.SetValue(get_embedding_enabled())
		self.embedding_summary = helper.addItem(wx.CheckBox(self, label=_("Use embeddings for page summaries")))
		self.embedding_summary.SetValue(get_embedding_page_summary_enabled())
		self.embedding_page_chat = helper.addItem(wx.CheckBox(self, label=_("Use embeddings for page chat")))
		self.embedding_page_chat.SetValue(get_embedding_page_chat_enabled())
		helper.addItem(wx.StaticText(self, label=_("Active embedding model:")))
		self.embedding_model = helper.addItem(wx.ComboBox(self, choices=[get_embedding_model() or defaults.DEFAULT_EMBEDDING_MODEL], style=wx.CB_READONLY))
		self.embedding_model.SetValue(get_embedding_model())
		manage = helper.addItem(wx.Button(self, label=_("Manage Embedding Models...")))
		manage.Bind(wx.EVT_BUTTON, self._on_manage_embeddings)
		self._embedding_catalog_task = background_tasks.submit(
			lambda _cancel: embedding_model_service.list_models(),
			on_success=self._on_embedding_models_loaded,
			is_alive=lambda: bool(self) and not self.IsBeingDeleted(),
		)

	def _on_embedding_models_loaded(self, models) -> None:
		selected = self.embedding_model.GetValue()
		choices = list(dict.fromkeys([selected, *(model.id for model in models)]))
		self.embedding_model.SetItems(choices)
		self.embedding_model.SetValue(selected)

	def _on_manage_embeddings(self, _event: wx.CommandEvent) -> None:
		from .embedding_model_dialog import open_embedding_model_dialog
		open_embedding_model_dialog(self.dialog)
		self.embedding_model.SetValue(get_embedding_model())

	def collect(self, values: dict[str, object]) -> None:
		values.update(
			num_ctx=self.parse_int(self.num_ctx, _("Context window size must be an integer of at least 256."), 256),
			temperature=self.parse_float(self.temperature, _("Temperature must be a number of at least 0."), 0.0),
			top_p=self.parse_float(self.top_p, _("Top-p must be a number between 0 and 1."), 0.0, 1.0),
			max_tokens=self.parse_int(self.max_tokens, _("Max tokens must be an integer of at least 1."), 1),
			embedding_enabled=self.embedding_enabled.GetValue(), embedding_summary=self.embedding_summary.GetValue(),
			embedding_page_chat=self.embedding_page_chat.GetValue(),
			embedding_model=self.embedding_model.GetValue().strip() or defaults.DEFAULT_EMBEDDING_MODEL,
		)


class AIAssistantBehaviorOutputPanel(_SettingsTab):
	title = _("Behavior & Output")

	def __init__(self, parent: wx.Window, dialog: "AIAssistantSettingsDialog") -> None:
		super().__init__(parent, dialog)
		helper = self.add_group(_("Behavior"))
		self.streaming = helper.addItem(wx.CheckBox(self, label=_("Enable streaming")))
		self.progress = helper.addItem(wx.CheckBox(self, label=_("Announce progress")))
		self.streaming_tone = helper.addItem(wx.CheckBox(self, label=_("Enable streaming tone feedback")))
		self.streaming.SetValue(get_streaming_enabled())
		self.progress.SetValue(get_progress_enabled())
		self.streaming_tone.SetValue(get_streaming_tone_enabled())
		helper.addItem(wx.StaticText(self, label=_("One-shot response output:")))
		self.one_shot_output = helper.addItem(wx.Choice(self, choices=[
			_("Speak, then display"), _("Display only"), _("Speak only"),
		]))
		self.one_shot_output.SetSelection(ONE_SHOT_OUTPUT_MODES.index(get_one_shot_output_mode()))
		help_text = _("Applies to summaries, image descriptions, and other one-shot responses, not chat. Speak only keeps focus in the current application. Show last result opens the latest answer in any mode.")
		self.one_shot_output.SetName(_("One-shot response output. ") + help_text)
		self.one_shot_output.SetToolTip(help_text)
		helper = self.add_group(_("Chat responses"))
		self.chat_auto_read = helper.addItem(wx.CheckBox(self, label=_("Automatically read completed chat responses")))
		self.chat_auto_read.SetValue(get_chat_auto_read())
		self.chat_auto_read.SetToolTip(_("Reads the completed answer aloud after it is displayed. Stopping speech does not cancel the request."))
		self.chat_status_announcements = helper.addItem(wx.CheckBox(self, label=_("Announce chat status changes")))
		self.chat_status_announcements.SetValue(get_chat_status_announcements())
		self.chat_status_announcements.SetToolTip(_("Announces message sent, generating response, response ready, stopped, and failures without reading the answer."))
		helper = self.add_group(_("Language & Image"))
		self.language_options = self._get_language_options()
		self.language = self.add_labeled_combo(helper, _("Prompt language:"), [label for _, label in self.language_options], self._language_label(get_language()))
		self.image_max_side = self.add_labeled_text(helper, _("Image max side length (pixels):"), get_image_max_side() or defaults.DEFAULT_IMAGE_MAX_SIDE)
		helper.addItem(wx.StaticText(self, label=_("Image format:")))
		self.image_format = helper.addItem(wx.Choice(self, choices=["PNG", "JPEG"]))
		self.image_format.SetSelection(0 if get_image_format() == "PNG" else 1)
		self.image_quality = self.add_labeled_text(helper, _("Image quality (JPEG only, 1-100):"), get_image_quality() or defaults.DEFAULT_IMAGE_QUALITY)

	def _get_language_options(self) -> list[tuple[str, str]]:
		template_dir = Path(__file__).resolve().parents[1] / "prompts" / "templates"
		options = [(defaults.DEFAULT_LANGUAGE, _("Automatic (use NVDA language)"))]
		if template_dir.exists():
			options.extend((child.name, child.name) for child in sorted(template_dir.iterdir()) if child.is_dir())
		return options

	def _language_label(self, value: str) -> str:
		return next((label for option, label in self.language_options if option == value), value)

	def collect(self, values: dict[str, object]) -> None:
		index = self.image_format.GetSelection()
		output_index = self.one_shot_output.GetSelection()
		if output_index not in range(len(ONE_SHOT_OUTPUT_MODES)):
			raise _InvalidSetting(_("Select a one-shot response output mode."), self.one_shot_output, self)
		if index not in (0, 1):
			raise _InvalidSetting(_("Image format must be PNG or JPEG."), self.image_format, self)
		quality = self.parse_int(self.image_quality, _("Image quality must be an integer between 1 and 100."), 1)
		if quality > 100:
			raise _InvalidSetting(_("Image quality must be an integer between 1 and 100."), self.image_quality, self)
		label = self.language.GetStringSelection()
		language = next((option for option, option_label in self.language_options if option_label == label), label)
		values.update(
			streaming=self.streaming.GetValue(), progress=self.progress.GetValue(), streaming_tone=self.streaming_tone.GetValue(), language=language,
			one_shot_output_mode=ONE_SHOT_OUTPUT_MODES[output_index],
			chat_auto_read=self.chat_auto_read.GetValue(), chat_status_announcements=self.chat_status_announcements.GetValue(),
			image_max_side=self.parse_int(self.image_max_side, _("Image max side length must be an integer of at least 128."), 128),
			image_format=["PNG", "JPEG"][index], image_quality=quality,
		)


class AIAssistantRuntimePanel(_SettingsTab):
	title = _("Runtime")

	def __init__(self, parent: wx.Window, dialog: "AIAssistantSettingsDialog") -> None:
		super().__init__(parent, dialog)
		helper = self.add_group(_("Runtime"))
		self.timeout = self.add_labeled_text(helper, _("Request timeout (seconds):"), get_timeout_seconds() or defaults.DEFAULT_TIMEOUT_SECONDS)
		self.litert_startup = self._add_startup_choice(helper, "litert-lm", _("LiteRT-LM startup"))
		self.llama_startup = self._add_startup_choice(helper, "llama-cpp-server", _("llama-server startup"))
		helper.addItem(wx.StaticText(self, label=_("Applies to the active provider the next time NVDA starts.")))

	def _add_startup_choice(self, helper: guiHelper.BoxSizerHelper, provider: str, label: str) -> wx.ComboBox:
		labels = [_("Start when needed (default)"), _("Prepare background worker at startup"), _("Start local server at startup")]
		descriptions = [
			_("Starts the worker on the first model operation and the server on the first inference request."),
			_("Prepares the background worker. The server starts on the first inference request."),
			_("Starts the background worker and local server. Model loading depends on the runtime."),
		]
		mode = get_local_startup_mode(provider)
		control = self.add_labeled_combo(helper, label, labels, labels[LOCAL_STARTUP_MODES.index(mode)])
		control.SetName(label)
		help_text = helper.addItem(wx.StaticText(self, label=""))

		def update_help(event=None):
			selection = control.GetSelection()
			text = descriptions[selection if 0 <= selection < len(descriptions) else 0]
			help_text.SetLabel(text)
			help_text.Wrap(self.FromDIP(560))
			# wx help text depends on a global help provider; include the
			# explanation in the accessible name so NVDA can announce it.
			control.SetName(f"{label}. {text}")
			control.SetHelpText(text)
			control.SetToolTip(text)
			self.Layout()
			if event is not None:
				event.Skip()

		control.Bind(wx.EVT_COMBOBOX, update_help)
		update_help()
		return control

	def _startup_mode(self, control: wx.ComboBox) -> str:
		selection = control.GetSelection()
		if not 0 <= selection < len(LOCAL_STARTUP_MODES):
			raise _InvalidSetting(_("Choose a startup option."), control, self)
		return LOCAL_STARTUP_MODES[selection]

	def collect(self, values: dict[str, object]) -> None:
		values.update(timeout_seconds=self.parse_float(self.timeout, _("Timeout seconds must be a positive number."), 0.000001), litert_startup=self._startup_mode(self.litert_startup), llama_startup=self._startup_mode(self.llama_startup))


class AIAssistantDiagnosticsPanel(_SettingsTab):
	title = _("Diagnostics")

	def __init__(self, parent: wx.Window, dialog: "AIAssistantSettingsDialog") -> None:
		super().__init__(parent, dialog)
		helper = self.add_group(_("Observability"))
		self.metrics_enabled = helper.addItem(wx.CheckBox(self, label=_("Enable request metrics logging")))
		self.metrics_enabled.SetValue(get_request_metrics_logging_enabled())
		self.metrics_path = self.add_labeled_text(helper, _("Metrics log file path:"), get_request_metrics_log_path())

	def collect(self, values: dict[str, object]) -> None:
		path = self.metrics_path.GetValue().strip()
		if self.metrics_enabled.GetValue() and not path:
			raise _InvalidSetting(_("Metrics log file path cannot be empty when logging is enabled."), self.metrics_path, self)
		values.update(metrics_enabled=self.metrics_enabled.GetValue(), metrics_path=path)


class AIAssistantSettingsDialog(SettingsDialog):
	title = _("AI Assistant Settings")
	helpId = "AIAssistantSettings"
	_panel_classes = (AIAssistantGeneralPanel, AIAssistantModelsContextPanel, AIAssistantBehaviorOutputPanel, AIAssistantRuntimePanel, AIAssistantDiagnosticsPanel, McpSettingsPanel)

	def __init__(self, parent: wx.Window, *, mcp_catalog: object = None, tool_registry: object = None, tool_executor: object = None) -> None:
		self.tabs: list[wx.Window] = []
		self._mcp_dependencies = (mcp_catalog, tool_registry, tool_executor)
		super().__init__(parent, resizeable=True, buttons={wx.OK, wx.CANCEL, wx.APPLY})
		self.Bind(wx.EVT_SHOW, self._on_show)

	def _on_show(self, event: wx.ShowEvent) -> None:
		event.Skip()
		if event.IsShown() and self.tabs:
			# SettingsDialog focuses its default button after construction. Put
			# keyboard focus on the active page so a keyboard user lands in the
			# settings content rather than on OK.
			wx.CallAfter(self._focus_current_page)

	def makeSettings(self, settingsSizer: wx.BoxSizer) -> None:
		self.notebook = wx.Notebook(self)
		settingsSizer.Add(self.notebook, flag=wx.EXPAND, proportion=1)
		for panel_class in self._panel_classes:
			if panel_class is McpSettingsPanel:
				if not all(self._mcp_dependencies):
					continue
				panel = panel_class(self.notebook, *self._mcp_dependencies)
			else:
				panel = panel_class(self.notebook, self)
			self.tabs.append(panel)
			self.notebook.AddPage(panel, panel_class.title)
		self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_page_changed)
		self._on_page_changed(None)

	def _on_page_changed(self, event: wx.BookCtrlEvent | None) -> None:
		if event is not None:
			event.Skip()
		if self.tabs:
			# Focus a panel is not focusable; move to its first usable control so
			# switching tabs with the keyboard does not drop focus on the floor.
			wx.CallAfter(self._focus_current_page)

	@staticmethod
	def _first_focusable(window: wx.Window) -> wx.Window | None:
		for child in window.GetChildren():
			if child.IsShown() and child.IsEnabled() and child.AcceptsFocus():
				return child
			candidate = AIAssistantSettingsDialog._first_focusable(child)
			if candidate is not None:
				return candidate
		return None

	def _focus_current_page(self) -> None:
		if not self.tabs:
			return
		page = self.notebook.GetPage(self.notebook.GetSelection())
		(self._first_focusable(page) or self.notebook).SetFocus()

	def show_validation_error(self, message: str, control: wx.Window, tab: wx.Window) -> None:
		wx.MessageBox(message, _("Invalid configuration"), wx.OK | wx.ICON_ERROR, parent=self)
		for index, candidate in enumerate(self.tabs):
			if candidate is tab:
				self.notebook.SetSelection(index)
				break
		control.SetFocus()

	def _collect_values(self) -> _SettingsValues:
		values: dict[str, object] = {}
		for tab in self.tabs:
			getattr(tab, "collect")(values)
		return _SettingsValues(**values)

	def _persist(self, values: _SettingsValues) -> None:
		set_provider(values.provider)
		set_model_name(values.model_name)
		set_embedding_enabled(values.embedding_enabled)
		set_embedding_page_summary_enabled(values.embedding_summary)
		set_embedding_page_chat_enabled(values.embedding_page_chat)
		set_embedding_model(values.embedding_model)
		set_num_ctx(values.num_ctx)
		set_generate_temperature(values.temperature)
		set_generate_top_p(values.top_p)
		set_generate_max_tokens(values.max_tokens)
		set_image_max_side(values.image_max_side)
		set_image_format(values.image_format)
		set_image_quality(values.image_quality)
		set_language(values.language)
		set_streaming_enabled(values.streaming)
		set_streaming_tone_enabled(values.streaming_tone)
		set_progress_enabled(values.progress)
		set_one_shot_output_mode(values.one_shot_output_mode)
		set_chat_auto_read(values.chat_auto_read)
		set_chat_status_announcements(values.chat_status_announcements)
		set_timeout_seconds(values.timeout_seconds)
		set_local_startup_mode("litert-lm", values.litert_startup)
		set_local_startup_mode("llama-cpp-server", values.llama_startup)
		set_request_metrics_logging_enabled(values.metrics_enabled)
		set_request_metrics_log_path(values.metrics_path)

	def _save(self, event: wx.CommandEvent, close: bool) -> None:
		try:
			values = self._collect_values()
		except _InvalidSetting as error:
			self.show_validation_error(str(error), error.control, error.tab)
			event.StopPropagation()
			return
		try:
			self._persist(values)
		except Exception as error:
			wx.MessageBox(_("Failed to save AI Assistant settings: {error}").format(error=error), _("Error"), wx.OK | wx.ICON_ERROR, parent=self)
			event.StopPropagation()
			return
		if close:
			super().onOk(event)
		else:
			super().onApply(event)

	def onOk(self, event: wx.CommandEvent) -> None:
		self._save(event, close=True)

	def onApply(self, event: wx.CommandEvent) -> None:
		self._save(event, close=False)


# Compatibility export for integrations that imported the former NVDA settings class.
AIAssistantSettingsPanel = AIAssistantGeneralPanel


def open_settings_dialog(parent: wx.Window, services: object = None) -> AIAssistantSettingsDialog:
	dialog = AIAssistantSettingsDialog(
		parent,
		mcp_catalog=getattr(services, "mcp_catalog", None),
		tool_registry=getattr(services, "tool_registry", None),
		tool_executor=getattr(services, "tool_executor", None),
	)
	try:
		dialog.ShowModal()
	finally:
		dialog.Destroy()
	return dialog
