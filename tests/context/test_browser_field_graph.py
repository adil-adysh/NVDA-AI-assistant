# -*- coding: utf-8 -*-
"""Pure graph extraction tests without an NVDA runtime."""
from __future__ import annotations

import sys
import types
import unittest

import pytest

from tests.support import ADDON_ROOT, load_module, register_package

pytestmark = pytest.mark.nvda_integration

ROOT = ADDON_ROOT / "context"
PACKAGE = "browser_graph_testpkg"
register_package(PACKAGE, ROOT)
register_package(f"{PACKAGE}.extractors", ROOT / "extractors")


load_module(f"{PACKAGE}.types", ROOT / "types.py")
try:
	parser_module = load_module(f"{PACKAGE}.extractors.browser_field_parser", ROOT / "extractors" / "browser_field_parser.py")
	BrowserFieldParser = parser_module.BrowserFieldParser
except ImportError:
	BrowserFieldParser = None
navigation_module = load_module(f"{PACKAGE}.navigation", ROOT / "navigation.py")
types_module = sys.modules[f"{PACKAGE}.types"]


class FieldCommand:
	def __init__(self, command: str, field: dict[str, object] | None = None) -> None:
		self.command = command
		self.field = field


class FakeTextInfo:
	def __init__(self, fields: list[object]) -> None:
		self._fields = fields

	def getTextWithFields(self):
		return self._fields


class FakeDocument:
	def __init__(self, fields: list[object]) -> None:
		self._fields = fields

	def makeTextInfo(self, _position: object) -> FakeTextInfo:
		return FakeTextInfo(self._fields)


class BrowserFieldGraphTests(unittest.TestCase):
	def test_graph_preserves_containment_and_sections(self) -> None:
		fields = [
			FieldCommand("controlStart", {"IAccessible2::attribute_tag": "main"}),
			FieldCommand("controlStart", {"IAccessible2::attribute_tag": "h2"}),
			"Getting Started",
			FieldCommand("controlEnd"),
			FieldCommand("controlStart", {"IAccessible2::attribute_tag": "a"}),
			"GitHub releases page",
			FieldCommand("controlEnd"),
			FieldCommand("controlEnd"),
		]
		parser = BrowserFieldParser()
		graph = parser.extract_graph(FakeDocument(fields), "Getting Started\nInstall from the release page")

		self.assertEqual([node.role for node in graph.nodes], ["landmark", "heading", "link"])
		self.assertEqual(graph.nodes[1].parent_id, graph.nodes[0].id)
		self.assertEqual(graph.nodes[2].parent_id, graph.nodes[0].id)
		self.assertEqual(graph.sections[0].title, "Getting Started")
		self.assertIn("Install from the release page", graph.sections[0].text)
		self.assertEqual(
			parser.structured_info_from_graph(graph)[1], ("GitHub releases page",)
		)

	def test_navigation_target_limit_is_hard_bound(self) -> None:
		graph = navigation_module.AccessibilityGraph(
			nodes=(types_module.AccessibilityNode("node-0", "heading", "Home", 0),)
		)
		self.assertEqual(navigation_module.build_navigation_targets(None, graph=graph, max_targets=0), ())

	def test_navigation_reads_nvda_accessible_name_before_legacy_label(self) -> None:
		self.assertEqual(
			navigation_module._node_label(types.SimpleNamespace(name="Search Results", label="")),
			"Search Results",
		)

	def test_navigation_uses_nvda_quick_nav_names(self) -> None:
		self.assertEqual(navigation_module._role_candidates("landmark"), ("landmark",))
		self.assertEqual(navigation_module._role_candidates("button"), ("button",))


if __name__ == "__main__":
	unittest.main()
