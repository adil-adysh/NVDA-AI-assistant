# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from tests.support import load_addon_module


types_module = load_addon_module("context.types", namespace="graph_store_tests")
graph_store_module = load_addon_module("context.graph_store", namespace="graph_store_tests")
save_accessibility_graph = graph_store_module.save_accessibility_graph
serialize_accessibility_graph = graph_store_module.serialize_accessibility_graph
AccessibilityGraph = types_module.AccessibilityGraph
AccessibilityNode = types_module.AccessibilityNode
SemanticSection = types_module.SemanticSection


class AccessibilityGraphStoreTests(unittest.TestCase):
	def setUp(self) -> None:
		self.graph = AccessibilityGraph(
			nodes=(AccessibilityNode(
				id="n1", role="button", name="Buy", order=0, text="Buy now",
			),),
			sections=(SemanticSection(
				id="s1", title="Checkout", text="Buy now", order=0,
				heading_node_id=None, node_ids=("n1",),
			),),
		)

	def test_serialization_is_versioned_and_contains_only_graph_values(self) -> None:
		payload = serialize_accessibility_graph(
			self.graph,
			captured_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
			title="Checkout", app_title="Chrome", source="browser",
		)

		self.assertEqual(payload["schema_version"], 1)
		self.assertEqual(payload["graph"]["nodes"][0]["name"], "Buy")
		self.assertEqual(payload["graph"]["sections"][0]["node_ids"], ["n1"])
		json.dumps(payload)

	def test_save_writes_json_with_ag_extension(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			path = save_accessibility_graph(
				self.graph, directory=Path(temp_dir), filename="sample.ag",
			)
			self.assertEqual(path.name, "sample.ag")
			self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["graph"]["nodes"][0]["id"], "n1")

	def test_save_rejects_path_traversal_and_wrong_extension(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			for filename in ("..\\escape.ag", "graph.json", "graph.ag.tmp"):
				with self.assertRaises(ValueError):
					save_accessibility_graph(self.graph, directory=Path(temp_dir), filename=filename)


if __name__ == "__main__":
	unittest.main()
