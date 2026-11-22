"""Gesture restoration must support both NVDA gesture registration layouts."""

import sys
import types

import pytest

from conftest import NVDA_SOURCE
from tests.support import ADDON_ROOT, load_module, register_package


@pytest.mark.parametrize("decorator_map", [False, True])
def test_layer_exit_restores_activation_gesture(monkeypatch, decorator_map):
	# Replace process-owned plugin/GUI composition; execute the real controller.
	namespace = "gesture_restoration_test"
	register_package(namespace, ADDON_ROOT)
	register_package(f"{namespace}.plugin", ADDON_ROOT / "plugin")
	application = types.ModuleType(f"{namespace}.plugin.application")
	application.AIAssistantApplication = object
	monkeypatch.setitem(sys.modules, application.__name__, application)
	garbage = types.ModuleType("garbageHandler")
	garbage.TrackedObject = object
	monkeypatch.setitem(sys.modules, "garbageHandler", garbage)
	base_object = load_module(f"{namespace}.baseObject", NVDA_SOURCE / "baseObject.py")
	plugin_api = types.ModuleType("globalPluginHandler")
	plugin_api.GlobalPlugin = base_object.ScriptableObject
	monkeypatch.setitem(sys.modules, "globalPluginHandler", plugin_api)
	for name in ("gui", "wx"):
		monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
	scripts = types.ModuleType("scriptHandler")
	scripts.script = lambda **kwargs: lambda function: function
	monkeypatch.setitem(sys.modules, "scriptHandler", scripts)
	controller = load_module(
		f"{namespace}.plugin.controller", ADDON_ROOT / "plugin" / "controller.py",
	)
	plugin_type = controller.GlobalPlugin
	activation = {"kb:NVDA+Shift+A": "assistantLayerCommands"}
	plugin_type._GlobalPlugin__gestures = {} if decorator_map else activation
	if decorator_map:
		plugin_type._scriptDecoratorGestures = activation
	plugin = object.__new__(plugin_type)
	bindings = {}
	plugin.bindGestures = bindings.update
	# Provider/model digit selection clears all bindings before layer exit.
	for _ in range(2):
		bindings.clear()
		plugin._restore_default_gesture_bindings()
		assert bindings == activation
	# Use real NVDA lookup code, including the global-map path which bypasses getScript.
	for name in ("NVDAObjects", "api", "queueHandler", "inputCore", "braille", "vision"):
		monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
	speech = types.ModuleType("speech")
	speech.sayAll = types.SimpleNamespace()
	monkeypatch.setitem(sys.modules, "speech", speech)
	monkeypatch.setitem(sys.modules, "baseObject", base_object)
	nvda_scripts = load_module(f"{namespace}.nvda_scriptHandler", NVDA_SOURCE / "scriptHandler.py")
	ui_boundary = types.ModuleType(f"{namespace}.ui.nvda_ui")
	ui_boundary.message = lambda _text: None
	register_package(f"{namespace}.ui", ADDON_ROOT / "ui")
	monkeypatch.setitem(sys.modules, ui_boundary.__name__, ui_boundary)
	layer_module = load_module(f"{namespace}.plugin.layer_mode", ADDON_ROOT / "plugin" / "layer_mode.py")
	calls = []
	layer = layer_module.AssistantLayerController(
		[("s", lambda _gesture: calls.append("summary"))],
		lambda key, script: bindings.update({key: script}), bindings.clear,
		plugin._restore_default_gesture_bindings,
	)
	plugin._app = types.SimpleNamespace(layer_mode=layer)
	layer.activate()
	gesture = types.SimpleNamespace(mainKeyName="s")
	nvda_scripts._getObjScript(plugin, gesture, [(plugin_type, bindings["kb:s"])])(gesture)
	assert calls == ["summary"]
	assert not layer.active
	assert bindings == activation
	layer.activate()
	token = layer.begin_choices("provider")
	layer.show_choices(token, "provider", [layer_module.Choice(str(i), str(i)) for i in range(23)], calls.append)
	for key in ("rightArrow", "rightArrow", "3"):
		gesture = types.SimpleNamespace(mainKeyName=key)
		nvda_scripts._getObjScript(plugin, gesture, [(plugin_type, bindings[f"kb:{key}"])])(gesture)
	assert calls[-1] == "22"
	assert not layer.active
	assert bindings == activation
	layer.activate()
	gesture = types.SimpleNamespace(mainKeyName="escape")
	nvda_scripts._getObjScript(plugin, gesture, [(plugin_type, bindings["kb:escape"])])(gesture)
	assert not layer.active
	assert bindings == activation
	# A provider notification fences immediately; its deferred binding cleanup
	# cannot dismiss a newly activated command session.
	deferred = []
	ui_boundary.queue = deferred.append
	layer.activate()
	token = layer.begin_choices("first")
	layer.provider_changed("second")
	assert not layer.accepts(token, "first")
	layer.activate()
	deferred.pop()()
	assert layer.active
	layer.finish()
