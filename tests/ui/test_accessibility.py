# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from tests.support import ADDON_ROOT, load_module


MODULE_PATH = ADDON_ROOT / "ui" / "accessibility.py"
MODULE_NAME = "ui_accessibility_test_module"


accessibility_module = load_module(MODULE_NAME, MODULE_PATH)


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

		def message_stub(_text):
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
