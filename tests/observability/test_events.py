"""Regression tests for privacy-safe diagnostic events."""
from __future__ import annotations

import unittest

from tests.support import load_addon_module


DiagnosticEvent = load_addon_module(
	"observability.events", namespace="observability_event_tests"
).DiagnosticEvent


class DiagnosticEventTests(unittest.TestCase):
	def test_sensitive_attributes_are_not_written(self) -> None:
		record = DiagnosticEvent(
			"task_completed",
			attributes={
				"task": "model_refresh",
				"prompt": "private page text",
				"api_key": "secret",
				"duration_ms": 12.5,
			},
		).to_record()
		self.assertEqual(record["attributes"], {"task": "model_refresh", "duration_ms": 12.5})


if __name__ == "__main__":
	unittest.main()
