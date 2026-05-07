# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "streaming_tone_progress_testpkg"


def _register_package(name: str, path: Path | None = None) -> types.ModuleType:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module
	return module


def _load_module(module_name: str, file_path: Path):
	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")
_register_package(f"{PACKAGE_NAME}.ui", ROOT_DIR / "ui")
_register_package(f"{PACKAGE_NAME}.observability", ROOT_DIR / "observability")
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")

log_module = types.ModuleType("logHandler")
log_module.log = types.SimpleNamespace(debug=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None)
sys.modules["logHandler"] = log_module

nvda_ui_module = types.ModuleType(f"{PACKAGE_NAME}.ui.nvda_ui")
nvda_ui_module.play_streaming_tone = lambda: None
nvda_ui_module.message = lambda text: None
nvda_ui_module.queue = lambda callback, *args: callback(*args)
sys.modules[nvda_ui_module.__name__] = nvda_ui_module

context_module = types.ModuleType(f"{PACKAGE_NAME}.observability.context")
context_module.ExecutionContext = object
sys.modules[context_module.__name__] = context_module

metrics_module = types.ModuleType(f"{PACKAGE_NAME}.observability.metrics")
metrics_module.RequestMetrics = object
sys.modules[metrics_module.__name__] = metrics_module

reporter_module = types.ModuleType(f"{PACKAGE_NAME}.observability.reporter")


class _Reporter:
	def report(self, metrics):
		return None


reporter_module.FileMetricsReporter = _Reporter
reporter_module.MetricsReporter = _Reporter
sys.modules[reporter_module.__name__] = reporter_module

config_settings_module = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
config_settings_module.is_progress_enabled = lambda: True
config_settings_module.is_streaming_enabled = lambda: True
sys.modules[config_settings_module.__name__] = config_settings_module

providers_interfaces_module = types.ModuleType(f"{PACKAGE_NAME}.providers.interfaces")
providers_interfaces_module.LLMProviderError = RuntimeError
sys.modules[providers_interfaces_module.__name__] = providers_interfaces_module

error_presentation_module = types.ModuleType(f"{PACKAGE_NAME}.service.error_presentation")
error_presentation_module.present_error = lambda error: types.SimpleNamespace(message=str(error))
sys.modules[error_presentation_module.__name__] = error_presentation_module

base_module = _load_module(
	f"{PACKAGE_NAME}.service.base",
	ROOT_DIR / "service" / "base.py",
)

BaseCoordinator = base_module.BaseCoordinator


class _TestCoordinator(BaseCoordinator):
	def _run_task_logic(self, progress_callback, *args, **kwargs):
		return None

	def _present_result(self, result):
		return None

	def _format_progress_message(self, generated_chars: int, preview: str) -> str:
		return f"{generated_chars}: {preview}"


class StreamingToneProgressTests(unittest.TestCase):
	def test_streaming_progress_plays_tone_even_when_progress_announcements_disabled(self) -> None:
		tone_calls: list[str] = []
		message_calls: list[str] = []

		base_module.is_progress_enabled = lambda: False
		base_module.nvda_ui.play_streaming_tone = lambda: tone_calls.append("tone")
		base_module.nvda_ui.message = lambda text: message_calls.append(text)

		coordinator = _TestCoordinator()

		coordinator._handle_progress("partial text", 120)

		self.assertEqual(tone_calls, ["tone"])
		self.assertEqual(message_calls, [])

	def test_zero_character_progress_does_not_play_tone(self) -> None:
		tone_calls: list[str] = []

		base_module.is_progress_enabled = lambda: False
		base_module.nvda_ui.play_streaming_tone = lambda: tone_calls.append("tone")

		coordinator = _TestCoordinator()

		coordinator._handle_progress("", 0)

		self.assertEqual(tone_calls, [])


if __name__ == "__main__":
	unittest.main()
