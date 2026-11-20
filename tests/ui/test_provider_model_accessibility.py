"""Behavior tests for accessible provider and model management controls."""
from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace

import pytest
import wx

from tests.support.settings_ui import load_settings_ui
from tests.support.bootstrap import ADDON_ROOT, load_addon_module, register_package


class _VisibilityStore:
	def __init__(self):
		self.disabled: set[str] = set()

	def get_disabled_models(self, _provider_id: str) -> set[str]:
		return set(self.disabled)

	def is_model_visible(self, _provider_id: str, model_id: str) -> bool:
		return model_id not in self.disabled

	def set_model_visible(self, _provider_id: str, model_id: str, visible: bool) -> None:
		if visible:
			self.disabled.discard(model_id)
		else:
			self.disabled.add(model_id)


@pytest.fixture
def model_manager(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	frame = wx.Frame(None)
	frame.Hide()
	load_settings_ui(monkeypatch)
	namespace = "provider_model_accessibility_tests"
	register_package(namespace, ADDON_ROOT)
	register_package(f"{namespace}.ui", ADDON_ROOT / "ui")
	nvda_ui = ModuleType(f"{namespace}.ui.nvda_ui")
	nvda_ui.queue = lambda *_args: None
	nvda_ui.message = lambda *_args: None
	monkeypatch.setitem(sys.modules, nvda_ui.__name__, nvda_ui)
	module = load_addon_module("ui.model_manager", namespace=namespace)
	store = _VisibilityStore()
	callbacks = []
	monkeypatch.setattr(module, "ModelVisibilityStore", lambda: store)
	monkeypatch.setattr(module.ModelManagerDialog, "_start_initial_load", lambda _self: None)
	monkeypatch.setattr(
		module.background_tasks,
		"submit",
		lambda _work, **kwargs: callbacks.append(kwargs["on_success"])
		or SimpleNamespace(done=False, cancel=lambda: None),
	)
	features = SimpleNamespace(download=True, delete=True, import_model=True)
	provider = SimpleNamespace(
		provider_id="test-provider",
		features=features,
		active_model_id="active-model",
		list_managed_models=lambda: [],
	)
	dialog = module.ModelManagerDialog(frame, provider, "Test Provider")
	try:
		yield app, module, dialog, store, callbacks
	finally:
		dialog.Destroy()
		frame.Destroy()
		app.ProcessPendingEvents()


def _models(module):
	return [
		module.ManagedModel(id="active-model", display_name="Active model", state=module.ModelState.READY, priority=1),
		module.ManagedModel(id="disabled-model", display_name="Disabled model", state=module.ModelState.DOWNLOADED, priority=2),
		module.ManagedModel(id="missing-model", display_name="Missing model", state=module.ModelState.NOT_DOWNLOADED, priority=3),
		module.ManagedModel(id="loading-model", display_name="Loading model", state=module.ModelState.DOWNLOADING, priority=4),
		module.ManagedModel(id="failed-model", display_name="Failed model", state=module.ModelState.FAILED, priority=5),
	]


def _load_models(dialog, models):
	dialog._on_models_fetched(models)


def _visible_model_ids(dialog):
	return {model.id for model in dialog._displayed_models}


def test_model_manager_omits_redundant_enabled_column_and_selects_active_model(model_manager):
	_app, module, dialog, store, _callbacks = model_manager
	store.disabled.add("disabled-model")
	_load_models(dialog, _models(module))

	assert dialog._enabled_filter.GetName() == "Filter by enabled state"
	assert dialog._availability_filter.GetName() == "Filter by model status"
	assert dialog._enabled_filter.GetStringSelection() == "All"
	assert dialog._availability_filter.GetStringSelection() == "All"
	assert [dialog._list.GetColumn(i).GetText() for i in range(4)] == ["Active", "Model", "Status", "Size"]
	assert dialog._get_selected_model().id == "active-model"
	assert dialog._list.GetFocusedItem() >= 0
	active_row = next(i for i in range(dialog._list.GetItemCount()) if dialog._list.GetItemText(i, 1) == "Active model")
	disabled_row = next(i for i in range(dialog._list.GetItemCount()) if dialog._list.GetItemText(i, 1) == "Disabled model")
	assert dialog._list.GetItemText(active_row, 0) == "Active"
	assert dialog._list.GetItemText(disabled_row, 0) == ""
	assert dialog._enable_btn.GetLabel() == "Enable"
	assert dialog._disable_btn.GetLabel() == "Disable"
	assert _visible_model_ids(dialog) == {"active-model", "disabled-model", "missing-model", "loading-model", "failed-model"}


def test_model_filters_combine_enabled_state_and_availability(model_manager):
	_app, module, dialog, store, _callbacks = model_manager
	store.disabled.update({"disabled-model", "loading-model"})
	_load_models(dialog, _models(module))

	dialog._enabled_filter.SetStringSelection("Disabled")
	dialog.Show()
	dialog._enabled_filter.SetFocus()
	_app.ProcessPendingEvents()
	dialog._availability_filter.SetStringSelection("Available")
	dialog._on_filter_change(None)
	assert _visible_model_ids(dialog) == {"disabled-model"}
	assert "Selected model is hidden" in dialog._filter_status.GetLabel()
	assert wx.Window.FindFocus() is dialog._enabled_filter

	dialog._availability_filter.SetStringSelection("Downloading")
	dialog._on_filter_change(None)
	assert _visible_model_ids(dialog) == {"loading-model"}

	dialog._enabled_filter.SetStringSelection("Enabled")
	dialog._availability_filter.SetStringSelection("Not downloaded")
	dialog._on_filter_change(None)
	assert _visible_model_ids(dialog) == {"missing-model"}


def test_selected_model_has_explicit_enable_disable_actions(model_manager):
	_app, module, dialog, store, _callbacks = model_manager
	store.disabled.add("disabled-model")
	_load_models(dialog, _models(module))
	dialog._select_displayed_model("active-model")
	assert dialog._enable_btn.IsEnabled() is False
	assert dialog._disable_btn.IsEnabled() is True

	dialog._select_displayed_model("disabled-model")
	assert dialog._enable_btn.IsEnabled() is True
	assert dialog._disable_btn.IsEnabled() is False

	dialog._enabled_filter.SetStringSelection("Disabled")
	dialog._on_filter_change(None)
	dialog._select_displayed_model("disabled-model")
	dialog._on_enable_model(None)
	assert store.is_model_visible("test-provider", "disabled-model") is True
	assert dialog._get_selected_model() is None
	assert dialog._enable_btn.IsEnabled() is False
	assert dialog._disable_btn.IsEnabled() is False


def test_native_settings_provider_controls_have_accessible_names(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	frame = wx.Frame(None)
	frame.Hide()
	module = load_settings_ui(monkeypatch)
	monkeypatch.setattr(module.AIAssistantGeneralPanel, "_refresh_status", lambda *_args: None)
	panel = module.AIAssistantGeneralPanel(frame, dialog=None)
	try:
		assert panel.provider_choice.GetName() == "Active provider"
		assert panel.model_combo.GetName() == "Active model"
	finally:
		frame.Destroy()
		app.ProcessPendingEvents()


def test_provider_catalog_selects_active_provider_and_restores_selection(model_manager, monkeypatch):
	_app, _model_module, _model_dialog, _store, _callbacks = model_manager
	gui_helper = ModuleType("gui.guiHelper")
	gui_helper.LabeledControlHelper = sys.modules["gui"].guiHelper.LabeledControlHelper
	monkeypatch.setitem(sys.modules, "gui.guiHelper", gui_helper)
	module = load_addon_module("ui.provider_dialog", namespace="provider_model_accessibility_tests")
	providers = [
		SimpleNamespace(id="first", name="First", kind="cloud", state="configured", enabled=True, active=False, actions=()),
		SimpleNamespace(id="active", name="Active", kind="cloud", state="configured", enabled=True, active=True, actions=()),
	]
	module.get_provider_infos = lambda: providers
	module.provider_kind_label = lambda value: str(value)
	module.provider_state_label = lambda value: str(value)
	frame = wx.Frame(None)
	frame.Hide()
	dialog = module.ProviderManagementDialog(frame)
	try:
		assert dialog._list.GetName() == "Provider catalog"
		assert dialog._selected_info().id == "active"
		assert dialog._list.GetFocusedItem() == 1
		dialog._list.Select(0, on=1)
		dialog._refresh_provider_list()
		assert dialog._selected_info().id == "first"
		assert dialog._list.GetFocusedItem() == 0
	finally:
		dialog.Destroy()
		frame.Destroy()
		_app.ProcessPendingEvents()


def test_llama_preset_list_selects_active_preset_on_first_load(model_manager):
	_app, _model_module, _model_dialog, _store, callbacks = model_manager
	module = load_addon_module("ui.llama_model_manager", namespace="provider_model_accessibility_tests")
	active = SimpleNamespace(
		model_id="active-preset",
		display_name="Active preset",
		repo="owner/active",
		file=None,
		draft_repo=None,
		draft_file=None,
		preset_options={},
	)
	provider = SimpleNamespace(
		provider_id="llama-cpp",
		active_model_id="active-preset",
		list_presets=lambda: [active],
		list_server_models=lambda **_kwargs: [],
	)
	frame = wx.Frame(None)
	frame.Hide()
	dialog = module.LlamaModelsDialog(frame, provider)
	try:
		callbacks[-1](([active], {"active-preset": {"value": "loaded"}}))
		assert dialog._list.GetName() == "Model presets"
		assert dialog._selected().model_id == "active-preset"
		assert dialog._list.GetFocusedItem() == 0
	finally:
		dialog.Destroy()
		frame.Destroy()
		_app.ProcessPendingEvents()
