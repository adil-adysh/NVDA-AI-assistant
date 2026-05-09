# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent / "accessibility.py"
MODULE_NAME = "ui_accessibility_test_module"


def _load_module():
	spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
	if spec is None or spec.loader is None:
		raise RuntimeError("Unable to load accessibility module")
	module = importlib.util.module_from_spec(spec)
	sys.modules[MODULE_NAME] = module
	spec.loader.exec_module(module)
	return module


accessibility_module = _load_module()


class AccessibilityAnnouncementTests(unittest.TestCase):
	def test_strip_html_for_announcement_returns_text_content(self) -> None:
		self.assertEqual(
			accessibility_module.strip_html_for_announcement("<p>Hello <strong>world</strong></p>"),
			"Hello world",
		)

	def test_queue_response_announcement_uses_first_non_empty_candidate(self) -> None:
		captured: list[tuple[object, str]] = []

		def queue_stub(func, text):
			captured.append((func, text))

		def message_stub(text):
			return None

		accessibility_module.queue_response_announcement(
			queue_stub,
			message_stub,
			"   ",
			None,
			"Final answer",
		)

		self.assertEqual(captured, [(message_stub, "Final answer")])


if __name__ == "__main__":
	unittest.main()
