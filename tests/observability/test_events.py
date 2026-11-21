"""Regression tests for privacy-safe diagnostic events."""
from __future__ import annotations

import unittest

from tests.support import load_addon_module


DiagnosticEvent = load_addon_module(
	"observability.events", namespace="observability_event_tests"
).DiagnosticEvent


class DiagnosticEventTests(unittest.TestCase):
	def test_sensitive_attributes_are_not_written(self) -> None:
		event = DiagnosticEvent(
			"task_completed",
			attributes={
				"task": "model_refresh",
				"prompt": "private page text",
				"api_key": "secret",
				"duration_ms": 12.5,
			},
		)
		record = event.to_record()
		self.assertEqual(record["attributes"], {"task": "model_refresh", "duration_ms": 12.5})
		self.assertEqual(record["record_type"], "task_event")
		self.assertEqual(record["schema_version"], 1)
		self.assertEqual(record["timestamp"], event.timestamp)

	def test_unknown_or_content_like_attributes_are_not_written(self) -> None:
		record = DiagnosticEvent(
			"task_completed",
			attributes={
				"task": "valid_task",
				"details": "private page text",
				"response_text": "model answer",
				"duration_ms": float("inf"),
			},
		).to_record()
		self.assertEqual(record["attributes"], {"task": "valid_task"})

	def test_event_metadata_rejects_untrusted_ids_and_error_values(self) -> None:
		record = DiagnosticEvent(
			"task_failed",
			operation_id="C:\\Users\\person\\private.txt",
			error_type="secret token value",
		).to_record()
		self.assertEqual(record["operation_id"], "unknown")
		self.assertNotIn("error_type", record)
		self.assertNotIn("thread", record)

	def test_local_callback_task_names_remain_useful(self) -> None:
		record = DiagnosticEvent(
			"task_started",
			attributes={"task": "AIAssistantGeneralPanel._refresh_models.<locals>.work"},
		).to_record()
		self.assertEqual(record["attributes"]["task"], "AIAssistantGeneralPanel._refresh_models.work")


if __name__ == "__main__":
	unittest.main()
