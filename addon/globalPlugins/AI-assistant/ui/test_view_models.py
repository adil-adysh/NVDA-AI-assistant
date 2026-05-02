# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

PACKAGE_NAME = "ui_testpkg"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)


def _load_module(module_name: str, file_name: str):
	spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{module_name}", MODULE_DIR / file_name)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module


intent = _load_module("intent", "intent.py")
view_models = _load_module("view_models", "view_models.py")

ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND = intent.ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND
DISPLAY_VARIANT_RESULT_ACTIONS = intent.DISPLAY_VARIANT_RESULT_ACTIONS
FOCUS_TARGET_PRIMARY_ACTION = intent.FOCUS_TARGET_PRIMARY_ACTION
TOOLBAR_ACTION_CLOSE = intent.TOOLBAR_ACTION_CLOSE
TOOLBAR_ACTION_COPY_MARKDOWN = intent.TOOLBAR_ACTION_COPY_MARKDOWN
TOOLBAR_ACTION_COPY_TEXT = intent.TOOLBAR_ACTION_COPY_TEXT
build_display_presentation = intent.build_display_presentation
DisplayResultViewModel = view_models.DisplayResultViewModel
ResultActionViewModel = view_models.ResultActionViewModel


class ViewModelTransportTests(unittest.TestCase):
	def test_display_result_transport_metadata_includes_display_presentation(self) -> None:
		view_model = DisplayResultViewModel(
			use_case_id="summary",
			title="Summary",
			output_text="Example",
			actions=(ResultActionViewModel(id="open_chat", label="Open Chat", kind="open_chat"),),
			display_presentation=build_display_presentation(
				variant=DISPLAY_VARIANT_RESULT_ACTIONS,
				initial_focus=FOCUS_TARGET_PRIMARY_ACTION,
				toolbar_actions=(TOOLBAR_ACTION_COPY_TEXT, TOOLBAR_ACTION_COPY_MARKDOWN, TOOLBAR_ACTION_CLOSE),
			),
			controls_visible=False,
			attention_policy=ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND,
		)

		metadata = view_model.transport_metadata()

		self.assertEqual(metadata["display_presentation"]["variant"], DISPLAY_VARIANT_RESULT_ACTIONS)
		self.assertEqual(metadata["display_presentation"]["initial_focus"], FOCUS_TARGET_PRIMARY_ACTION)
		self.assertEqual(metadata["display_presentation"]["toolbar"]["actions"], [TOOLBAR_ACTION_COPY_TEXT, TOOLBAR_ACTION_COPY_MARKDOWN, TOOLBAR_ACTION_CLOSE])
		self.assertEqual(metadata["controls_visible"], False)
		self.assertEqual(metadata["attention_policy"], ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND)
		self.assertEqual(metadata["actions"][0]["id"], "open_chat")


if __name__ == "__main__":
	unittest.main()
