"""Optional integration coverage requiring a built sibling NVDA checkout."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

from conftest import NVDA_ROOT, NVDA_SOURCE
from tests.support import load_addon_module


pytestmark = pytest.mark.nvda_integration

NVDA_HELPER = NVDA_SOURCE / "lib" / "x64" / "nvdaHelperLocal.dll"
if not NVDA_HELPER.is_file():
	pytest.skip(
		"Built NVDA native helpers were not found; build ../nvda before running integration tests",
		allow_module_level=True,
	)


@pytest.fixture(scope="module", autouse=True)
def _standalone_process_services():
	"""Provide only process-owned audio/speech surfaces absent outside NVDA."""
	from monkeyPatches.comtypesMonkeyPatches import appendComInterfacesToGenSearchPath
	import config

	appendComInterfacesToGenSearchPath()
	if config.conf is None:
		config.initialize()
	saved = {name: sys.modules.get(name) for name in ("gui", "nvwave", "ui")}
	nvwave = types.ModuleType("nvwave")
	nvwave.WavePlayer = object
	nvwave.AudioPurpose = SimpleNamespace(SOUNDS="sounds")
	nvwave.playWaveFile = lambda *_args, **_kwargs: None
	nvda_ui = types.ModuleType("ui")
	nvda_ui.message = lambda *_args, **_kwargs: None
	nvda_ui.nh3 = SimpleNamespace(clean=lambda value: value)
	gui = types.ModuleType("gui")
	gui.__path__ = [str(NVDA_SOURCE / "gui")]
	gui.mainFrame = SimpleNamespace()
	sys.modules["nvwave"] = nvwave
	sys.modules["ui"] = nvda_ui
	sys.modules["gui"] = gui
	try:
		yield
	finally:
		for name, module in saved.items():
			if module is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = module


def test_runtime_bound_nvda_modules_import_from_sibling_checkout() -> None:
	for name in ("api", "globalPluginHandler", "queueHandler"):
		module = importlib.import_module(name)
		assert module.__file__ is not None
		assert Path(module.__file__).resolve().is_relative_to(NVDA_ROOT.resolve())


def test_nvda_ui_uses_real_event_queue_contract() -> None:
	queue_handler = importlib.import_module("queueHandler")
	nvda_ui = load_addon_module("ui.nvda_ui", namespace="built_nvda_ui_tests")
	assert nvda_ui.queueHandler is queue_handler
	assert callable(queue_handler.queueFunction)
	assert nvda_ui.queue.__module__ == "built_nvda_ui_tests.ui.nvda_ui"


def test_plugin_controller_imports_against_built_nvda_runtime() -> None:
	global_plugin_handler = importlib.import_module("globalPluginHandler")
	controller = load_addon_module("plugin.controller", namespace="built_nvda_addon")

	assert issubclass(controller.GlobalPlugin, global_plugin_handler.GlobalPlugin)
	# Importing the controller creates the UI adapter singleton. Clean it up so
	# the integration process has no lingering worker thread.
	adapter = importlib.import_module("built_nvda_addon.ui.adapter").ui_adapter
	adapter.close()
